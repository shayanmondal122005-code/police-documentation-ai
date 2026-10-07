"""Resolve server-managed credentials without copying them into session state."""

import streamlit as st

from config import get_api_key


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
