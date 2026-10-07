"""Central configuration for Police Documentation AI.

All model names, limits, supported formats and timeouts live here. Nothing in
this module reads or stores secrets other than the *name* of the API-key
environment variable; the key itself is read lazily by `get_api_key`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Police Documentation AI"
APP_VERSION = "0.1.0"
REPORT_TITLE = "POLICE FIELD INTERACTION REPORT"

AI_DRAFT_WARNING = "AI-GENERATED DRAFT — REQUIRES OFFICER REVIEW"
NOT_OFFICIAL_NOTICE = (
    "This document is an AI-generated draft. It is not an official police record "
    "until reviewed, corrected and adopted by the responsible officer."
)
HASH_DISCLAIMER = (
    "The SHA-256 hash identifies the uploaded file and can help detect later file "
    "changes. This MVP is NOT a complete forensic chain-of-custody system."
)
PRIVACY_NOTICE = (
    "Audio and transcript text are sent to Groq for processing. Review Groq's data "
    "controls before uploading sensitive information. This MVP is NOT production-ready "
    "for real police evidence."
)

API_KEY_ENV_VAR = "GROQ_API_KEY"

# --- Models (verified 2026-10-07; see docs/GROQ_API_RESEARCH.md)
TRANSCRIPTION_MODEL = os.getenv("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3")
REPORT_MODEL = os.getenv("GROQ_REPORT_MODEL", "openai/gpt-oss-120b")
SUPPORTED_TRANSCRIPTION_MODELS = ("whisper-large-v3", "whisper-large-v3-turbo")
SUPPORTED_REPORT_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")


@dataclass(frozen=True)
class GroqModels:
    transcription: str = TRANSCRIPTION_MODEL
    report: str = REPORT_MODEL

# --- Transcription engines offered in the UI
ENGINE_GROQ = "groq"
ENGINE_MOCK = "mock"
ENGINE_LABELS = {
    ENGINE_GROQ: "Groq Whisper — multilingual transcription",
    ENGINE_MOCK: "Mock — local demo transcript (no API key, no audio sent)",
}

# --- Upload limits and formats
MAX_UPLOAD_MB = 25
# Use a conservative decimal cap for Groq's documented 25 MB direct-attachment limit.
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1_000_000
HASH_CHUNK_BYTES = 1024 * 1024

SUPPORTED_AUDIO_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".mpeg": "audio/mpeg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".mpga": "audio/mpeg",
}
SUPPORTED_EXTENSIONS = tuple(ext.lstrip(".") for ext in SUPPORTED_AUDIO_TYPES)

# --- Timeouts (seconds) and retries
REQUEST_TIMEOUT_SECONDS = 180
API_MAX_RETRIES = 2
REPORT_MAX_ATTEMPTS = 2
REPORT_MAX_COMPLETION_TOKENS = 4096


def get_api_key() -> str | None:
    """Return the Groq API key from the environment, or None if unset/blank."""
    key = os.getenv(API_KEY_ENV_VAR, "").strip()
    return key or None
