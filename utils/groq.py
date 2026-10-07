"""Groq client, strict JSON schemas and safe error messages.

Never log raw API responses, credentials, audio or transcript text.
"""

from __future__ import annotations

import logging
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


def request_error_kind(exc: Exception) -> str | None:
    """Classify known request errors without exposing provider text or generated data.

    The SDK may receive either a wrapped or flat error object. Messages are only
    inspected for fixed signatures; neither messages nor arbitrary codes escape.
    """
    if not isinstance(exc, groq.APIStatusError) or exc.status_code not in (400, 413, 422):
        return None
    body = exc.body
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    message = error.get("message", "")
    message = message.lower() if isinstance(message, str) else ""
    # Account, size and policy failures must never trigger a format retry.
    if code == "blocked_api_access":
        return "account_limit"
    if code in ("content_policy_violation", "content_filter", "permission_denied"):
        return "policy"
    if code in ("context_length_exceeded", "request_too_large", "tokens_limit_exceeded"):
        return "text_limit"
    if "tokens per minute" in message or "context length" in message or "maximum context" in message:
        return "text_limit"
    if code in ("json_validate_failed", "invalid_json_schema", "json_schema_invalid",
                "schema_validation_failed", "unsupported_response_format"):
        return "report_format"
    if code in (None, "invalid_request_error") and (
        error.get("param") in ("response_format", "response_format.json_schema", "response_format.json_schema.schema")
        or (("json schema" in message or "json_schema" in message or "response_format" in message)
            and any(word in message for word in ("invalid", "unsupported", "not supported", "failed to compile")))
    ):
        return "report_format"
    return None


def translate_error(exc: Exception, error_cls: type[UserFacingError], action: str) -> UserFacingError:
    if isinstance(exc, UserFacingError):
        return exc
    code = exc.status_code if isinstance(exc, groq.APIStatusError) else None
    kind = request_error_kind(exc)
    report_request = "report" in action.lower() or "connection check" in action.lower()
    logger.error("%s failed: %s (HTTP %s; category %s)", action, type(exc).__name__, code or "n/a", kind or "unknown")
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
        elif code in (400, 413, 422) and kind == "account_limit":
            message = "Groq blocked API access because of an account limit. Check account/spend limits in Groq Console."
        elif code in (400, 413, 422) and kind == "policy":
            message = "Groq rejected the request under its access or content policy. No report was accepted."
        elif code in (400, 413, 422) and (kind == "text_limit" or (code == 413 and report_request)):
            message = "the report text or requested output exceeds Groq's token/context limit. Use a shorter recording and check Console token limits."
        elif code == 413:
            message = "the request is too large. Audio uploads must be under 25 MB; use a shorter recording."
        elif code in (408, 504):
            message = "Groq timed out. Retry with a shorter recording."
        elif code in (400, 422):
            if report_request and kind == "report_format":
                message = "Groq rejected the report's JSON format. No report was accepted. Try again with a short recording."
            elif report_request:
                message = "Groq rejected the report request. Check report-model settings and Console limits. The failed step uses transcript text, not an audio upload."
            else:
                message = "Groq rejected the audio request. Check transcription-model settings and try a short, valid WAV or MP3 recording."
        elif code >= 500:
            message = "the Groq service is temporarily unavailable after retries. Try again later."
        else:
            message = "Groq could not complete the request. Check Console settings and try again later."
        return error_cls(f"{action} failed: {message} (HTTP {code})")
    return error_cls(f"{action} failed unexpectedly. No sensitive details are shown.")


def check_model_connection(api_key: str, models: GroqModels) -> None:
    """Test the actual report schema with fictional text, never uploaded audio.

    Import lazily because report clients also use this module's SDK helpers.
    """
    from documentation.clients import GroqReportClient
    from documentation.report_generator import request_analysis
    from transcription.base import TranscriptResult

    validate_models(models)
    client = create_client(api_key)
    try:
        request_analysis(
            TranscriptResult(raw_transcript="This is a fictional connection test. No incident is being reported."),
            GroqReportClient(client=client, model=models.report),
        )
    except Exception as exc:
        raise translate_error(exc, ConfigurationError, "Groq connection check") from exc
    finally:
        close_client(client)
