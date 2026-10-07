"""Resolve server-managed credentials without copying them into session state."""

import os

import streamlit as st

from config import API_KEY_ENV_VAR, GroqModels, get_api_key


def app_api_key() -> str | None:
    key = get_api_key()
    if key:
        return key
    try:
        value = st.secrets.get(API_KEY_ENV_VAR, "")
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


def app_models() -> GroqModels:
    """Read model overrides per request from env first, then Streamlit Secrets."""
    defaults = GroqModels()
    return GroqModels(
        transcription=_model_setting("GROQ_TRANSCRIPTION_MODEL", defaults.transcription) or defaults.transcription,
        report=_model_setting("GROQ_REPORT_MODEL", defaults.report) or defaults.report,
    )
