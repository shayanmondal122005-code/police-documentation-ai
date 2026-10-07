"""Shared Gemini SDK helpers: client creation, file upload/cleanup and error translation.

Error messages produced here are deliberately generic: raw API responses, request
contents and stack traces are never surfaced to the user or written to logs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config import (
    API_KEY_ENV_VAR,
    FILE_POLL_INTERVAL_SECONDS,
    FILE_PROCESSING_TIMEOUT_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    get_api_key,
)
from errors import ConfigurationError, UserFacingError

logger = logging.getLogger(__name__)


def create_client(api_key: str | None = None) -> genai.Client:
    """Create a Gemini client from GEMINI_API_KEY; raise ConfigurationError if it is missing."""
    api_key = api_key or get_api_key()
    if not api_key:
        raise ConfigurationError(
            f"No Gemini API key found. Set {API_KEY_ENV_VAR} in your .env file "
            "(see .env.example), or choose the Mock engine for a local demo."
        )
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_SECONDS * 1000),
    )


def simplify_schema(schema: Any) -> Any:
    """Strip Pydantic's `title`/`default` keys, which Gemini's schema subset does not need."""
    if isinstance(schema, dict):
        return {
            key: simplify_schema(value)
            for key, value in schema.items()
            if key not in ("title", "default") or not isinstance(value, (str, int, float, bool, type(None), list))
        }
    if isinstance(schema, list):
        return [simplify_schema(item) for item in schema]
    return schema


def translate_error(exc: Exception, error_cls: type[UserFacingError], action: str) -> UserFacingError:
    """Map an SDK/network exception to a safe, human-readable error of type `error_cls`.

    Only the exception *class* and HTTP status are logged, never the message body.
    """
    code = exc.code if isinstance(exc, genai_errors.APIError) else None
    logger.error("%s failed: %s (HTTP %s)", action, type(exc).__name__, code or "n/a")
    if isinstance(exc, UserFacingError):
        return exc
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return error_cls(f"{action} timed out. Try again, or use a shorter recording.")
    if isinstance(exc, (httpx.TransportError, ConnectionError)):
        return error_cls(f"{action} failed because the network connection to Gemini was lost.")
    if isinstance(exc, genai_errors.APIError):
        return error_cls(f"{_api_error_message(exc, action)} (HTTP {exc.code})")
    return error_cls(f"{action} failed unexpectedly. No details are shown to protect sensitive data.")


def _api_error_message(exc: genai_errors.APIError, action: str) -> str:
    code = getattr(exc, "code", None)
    text = (getattr(exc, "message", "") or "").lower()
    if code in (401, 403) or "api key" in text:
        return f"{action} failed: the Gemini API key was rejected. Check {API_KEY_ENV_VAR} in .env or Streamlit Secrets."
    if code == 429:
        return f"{action} failed: Gemini rate limit or quota reached. Wait a minute and try again."
    if code == 404:
        return f"{action} failed: the configured Gemini model is unavailable for this API key. Check the model settings and access in Google AI Studio."
    if code in (408, 504) or "deadline" in text:
        return f"{action} timed out on the Gemini side. Try again, or use a shorter recording."
    if code == 400:
        return (
            f"{action} failed: Gemini could not process this recording or request "
            "(it may be corrupted, in an unsupported codec, or too long)."
        )
    if isinstance(code, int) and code >= 500:
        return f"{action} failed: the Gemini service is temporarily unavailable. Retry later or select another supported model in the model settings."
    return f"{action} failed due to a Gemini API error."


def generate_with_fallback(
    client: genai.Client, *, model: str, contents: Any, config: types.GenerateContentConfig,
    error_cls: type[UserFacingError], action: str, fallback_model: str | None = None,
) -> tuple[Any, str]:
    """Use one compatible fallback after SDK retries exhaust on 500/502/503.

    Reuse the exact input and schema. Never change models for invalid requests,
    credentials, quota, safety blocks, or Files API failures. Dedicated ASR callers
    leave fallback_model unset because Flash does not accept ASR configuration.
    """
    attempted = [model]
    try:
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return response, model
        except genai_errors.APIError as exc:
            if exc.code not in (500, 502, 503) or not fallback_model or fallback_model == model:
                raise
            logger.warning("%s primary failed (HTTP %s); trying configured fallback", action, exc.code)
        attempted.append(fallback_model)
        response = client.models.generate_content(model=fallback_model, contents=contents, config=config)
        return response, fallback_model
    except Exception as exc:
        translated = translate_error(exc, error_cls, f"{action} (model generation)")
        raise error_cls(f"{translated.user_message} Models attempted: {', '.join(attempted)}.") from exc


def check_model_connection(api_key: str, model: str) -> None:
    """A user-triggered, text-only check; it does not test audio upload/transcription."""
    client = create_client(api_key)
    try:
        response, _ = generate_with_fallback(
            client, model=model, contents="Reply with OK.", config=types.GenerateContentConfig(),
            error_cls=ConfigurationError, action="Connection test",
        )
        if not (response.text or "").strip():
            raise ConfigurationError("Connection test received no text. Audio transcription has not been tested.")
    finally:
        try:
            client.close()
        except Exception as exc:
            logger.warning("Could not close Gemini client: %s", type(exc).__name__)


def upload_audio(client: genai.Client, audio_path: Path, mime_type: str) -> Any:
    """Upload audio through the Files API and wait until it is ready to use."""
    uploaded = client.files.upload(file=str(audio_path), config=types.UploadFileConfig(mime_type=mime_type))
    try:
        deadline = time.monotonic() + FILE_PROCESSING_TIMEOUT_SECONDS
        while _state_name(uploaded) == "PROCESSING":
            if time.monotonic() > deadline:
                raise TimeoutError("file processing timed out")
            time.sleep(FILE_POLL_INTERVAL_SECONDS)
            uploaded = client.files.get(name=uploaded.name)
        if _state_name(uploaded) == "FAILED":
            raise ValueError("file processing failed")
    except Exception:
        delete_uploaded_file(client, uploaded)
        raise
    return uploaded


def _state_name(file_obj: Any) -> str:
    state = getattr(file_obj, "state", None)
    return str(getattr(state, "name", state) or "").upper()


def delete_uploaded_file(client: genai.Client, file_obj: Any) -> None:
    """Best-effort removal of the uploaded recording from Google's file store."""
    try:
        client.files.delete(name=file_obj.name)
    except Exception as exc:  # noqa: BLE001 - cleanup must never mask the real result
        logger.warning("Could not delete uploaded file: %s", type(exc).__name__)


@contextmanager
def uploaded_audio(client: genai.Client, audio_path: Path, mime_type: str) -> Iterator[Any]:
    """Upload audio for the duration of the `with` block, then delete it remotely."""
    file_obj = upload_audio(client, audio_path, mime_type)
    try:
        yield file_obj
    finally:
        delete_uploaded_file(client, file_obj)
