"""Groq client, strict JSON schemas and safe error messages.

Never log raw API responses, credentials, audio or transcript text.
"""

from __future__ import annotations

import logging
import json
from typing import Any

import groq
import httpx

from config import API_MAX_RETRIES, REQUEST_TIMEOUT_SECONDS, GroqModels, SUPPORTED_REPORT_MODELS, SUPPORTED_TRANSCRIPTION_MODELS, get_api_key
from errors import ConfigurationError, UserFacingError

logger = logging.getLogger(__name__)


def validate_models(models: GroqModels) -> None:
    if models.transcription not in SUPPORTED_TRANSCRIPTION_MODELS:
        raise ConfigurationError("Set GROQ_TRANSCRIPTION_MODEL to whisper-large-v3 or whisper-large-v3-turbo.")
    if models.report not in SUPPORTED_REPORT_MODELS:
        raise ConfigurationError("Set GROQ_REPORT_MODEL to openai/gpt-oss-120b or openai/gpt-oss-20b for strict structured reports.")


def create_client(api_key: str | None = None) -> groq.Groq:
    key = (api_key or get_api_key() or "").strip()
    if not key:
        raise ConfigurationError("No Groq API key found. Set GROQ_API_KEY in .env or Streamlit Secrets, or choose the fictional demo.")
    return groq.Groq(
        api_key=key,
        timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=20.0, write=60.0),
        max_retries=API_MAX_RETRIES,
    )


def close_client(client: Any) -> None:
    """Cleanup must not replace a successful result or the original safe error."""
    try:
        client.close()
    except Exception as exc:
        logger.warning("Could not close Groq client: %s", type(exc).__name__)


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy a Pydantic schema into Groq's strict subset, preserving nullable types.

    Walk schema nodes explicitly so field names such as `title` are not stripped.
    All properties are required, including nullable ones, and every object is closed.
    """
    result = {key: value for key, value in schema.items() if key not in ("title", "default")}
    for key in ("properties", "$defs", "definitions"):
        if key in result:
            result[key] = {name: strict_schema(node) for name, node in result[key].items()}
    for key in ("anyOf", "oneOf", "allOf"):
        if key in result:
            result[key] = [strict_schema(node) for node in result[key]]
    if isinstance(result.get("items"), dict):
        result["items"] = strict_schema(result["items"])
    if result.get("type") == "object" or "properties" in result:
        result["required"] = list(result.get("properties", {}))
        result["additionalProperties"] = False
    return result


def translate_error(exc: Exception, error_cls: type[UserFacingError], action: str) -> UserFacingError:
    if isinstance(exc, UserFacingError):
        return exc
    code = exc.status_code if isinstance(exc, groq.APIStatusError) else None
    logger.error("%s failed: %s (HTTP %s)", action, type(exc).__name__, code or "n/a")
    if isinstance(exc, (groq.APITimeoutError, httpx.TimeoutException, TimeoutError)):
        return error_cls(f"{action} timed out. Retry with a shorter recording.")
    if isinstance(exc, (groq.APIConnectionError, httpx.TransportError, ConnectionError)):
        return error_cls(f"{action} failed because the connection to Groq was lost. Try again later.")
    if code is not None:
        if code == 401:
            message = "the Groq API key was rejected. Check GROQ_API_KEY in .env or Streamlit Secrets."
        elif code == 403:
            message = "Groq denied access. Check the project's model permissions in Groq Console."
        elif code == 404:
            message = "the configured Groq model is unavailable. Check model settings and permissions in Groq Console."
        elif code == 429:
            message = "Groq rate limit or quota reached. Check Console limits, wait before retrying, or use a shorter recording."
        elif code == 413:
            message = "the request is too large. Audio uploads must be under 25 MB; use a shorter recording."
        elif code in (408, 504):
            message = "Groq timed out. Retry with a shorter recording."
        elif code in (400, 422):
            message = "Groq rejected the audio or request. Check model settings and try a short, valid WAV or MP3 recording."
        elif code >= 500:
            message = "the Groq service is temporarily unavailable after retries. Try again later."
        else:
            message = "Groq could not complete the request. Check Console settings and try again later."
        return error_cls(f"{action} failed: {message} (HTTP {code})")
    return error_cls(f"{action} failed unexpectedly. No sensitive details are shown.")


def check_model_connection(api_key: str, models: GroqModels) -> None:
    """User-triggered text/JSON probe; audio is only tested by processing a recording."""
    validate_models(models)
    client = create_client(api_key)
    try:
        response = client.chat.completions.create(
            model=models.report,
            messages=[{"role": "user", "content": 'Return JSON with "ok" set to true.'}],
            reasoning_effort="low",
            max_completion_tokens=512,
            response_format={"type": "json_schema", "json_schema": {
                "name": "connection_check", "strict": True,
                "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                           "required": ["ok"], "additionalProperties": False},
            }},
        )
        if not response.choices or not response.choices[0].message.content:
            raise ConfigurationError("Groq returned no text. Audio transcription has not been tested.")
        choice = response.choices[0]
        if choice.finish_reason != "stop" or getattr(choice.message, "refusal", None):
            raise ConfigurationError("Groq did not complete the connection check. Audio transcription has not been tested.")
        try:
            valid = json.loads(choice.message.content).get("ok") is True
        except (ValueError, AttributeError):
            valid = False
        if not valid:
            raise ConfigurationError("Groq did not return the expected check response. Audio transcription has not been tested.")
    except Exception as exc:
        raise translate_error(exc, ConfigurationError, "Groq connection check") from exc
    finally:
        close_client(client)
