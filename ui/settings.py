"""Resolve server-managed credentials without copying them into session state."""

import os

import streamlit as st

from config import GeminiModels, get_api_key


def app_api_key() -> str | None:
    key = get_api_key()
    if key:
        return key
    try:
        value = st.secrets.get("GEMINI_API_KEY", "")
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return None
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _model_setting(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        try:
            value = st.secrets.get(name, default)
        except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
            value = default
    return value.strip() if isinstance(value, str) else default


def app_models() -> GeminiModels:
    """Read model overrides per request from env first, then Streamlit Secrets."""
    defaults = GeminiModels()
    return GeminiModels(
        prompted=_model_setting("GEMINI_TRANSCRIPTION_MODEL", defaults.prompted) or defaults.prompted,
        asr=_model_setting("GEMINI_ASR_MODEL", defaults.asr) or defaults.asr,
        report=_model_setting("GEMINI_REPORT_MODEL", defaults.report) or defaults.report,
        fallback=_model_setting("GEMINI_FALLBACK_MODEL", defaults.fallback),
    )
