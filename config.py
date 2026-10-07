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
    "Audio and transcript text are sent to Google's Gemini API for processing. "
    "On the Gemini API free tier, Google may use submitted content to improve its "
    "products. This MVP is NOT production-ready for real police evidence."
)

API_KEY_ENV_VAR = "GEMINI_API_KEY"

# --- Models (verified against official docs on 2026-10-07; see docs/GEMINI_API_RESEARCH.md)
PROMPTED_TRANSCRIPTION_MODEL = os.getenv("GEMINI_TRANSCRIPTION_MODEL", "gemini-3.8-flash")
ASR_TRANSCRIPTION_MODEL = os.getenv("GEMINI_ASR_MODEL", "gemini-3.5-transcribe")
REPORT_MODEL = os.getenv("GEMINI_REPORT_MODEL", "gemini-3.8-flash")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.7-flash")


@dataclass(frozen=True)
class GeminiModels:
    prompted: str = PROMPTED_TRANSCRIPTION_MODEL
    asr: str = ASR_TRANSCRIPTION_MODEL
    report: str = REPORT_MODEL
    fallback: str = FALLBACK_MODEL

# --- Transcription engines offered in the UI
ENGINE_PROMPTED = "prompted"
ENGINE_ASR = "asr"
ENGINE_MOCK = "mock"
ENGINE_LABELS = {
    ENGINE_PROMPTED: "Gemini Flash — prompted (Hindi/Bhojpuri instructions)",
    ENGINE_ASR: "Gemini 3.5 Transcribe — dedicated ASR (speaker labels, word times)",
    ENGINE_MOCK: "Mock — local demo transcript (no API key, no audio sent)",
}
ASR_TIMESTAMP_DIARIZATION_MAX_MINUTES = 30

# --- Upload limits and formats
MAX_UPLOAD_MB = 200
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024

SUPPORTED_AUDIO_TYPES: dict[str, str] = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/m4a",
    ".mp4": "video/mp4",
    ".mpeg": "audio/mpeg",
    ".webm": "audio/webm",
}
SUPPORTED_EXTENSIONS = tuple(ext.lstrip(".") for ext in SUPPORTED_AUDIO_TYPES)

# --- Timeouts (seconds) and retries
REQUEST_TIMEOUT_SECONDS = 600
FILE_PROCESSING_TIMEOUT_SECONDS = 180
FILE_POLL_INTERVAL_SECONDS = 2
REPORT_MAX_ATTEMPTS = 2

# Generation uses the model's default sampling settings, as recommended for Gemini 3.x.


def get_api_key() -> str | None:
    """Return the Gemini API key from the environment, or None if unset/blank."""
    key = os.getenv(API_KEY_ENV_VAR, "").strip()
    return key or None
