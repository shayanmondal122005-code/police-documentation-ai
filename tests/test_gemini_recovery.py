"""Recovery regressions with no credentials or network calls."""

from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from config import GeminiModels
from documentation.clients import GeminiReportClient
from errors import ConfigurationError, ReportGenerationError, TranscriptionError
from tests.test_app_readiness import ROOT
from tests.test_transcription import FakeFiles, api_error, prompted_json
from transcription.gemini_transcriber import GeminiASRTranscriber, GeminiPromptedTranscriber
from utils.gemini import check_model_connection


class ScriptedModels:
    def __init__(self, *outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client_with(*outcomes):
    return SimpleNamespace(files=FakeFiles(), models=ScriptedModels(*outcomes))


@pytest.mark.parametrize("code", [500, 502, 503])
def test_prompted_recovers_using_same_upload_prompt_and_schema(tmp_path, code):
    client = client_with(api_error(code, "UNAVAILABLE", "private response"),
                         SimpleNamespace(text=prompted_json()))
    result = GeminiPromptedTranscriber(client).transcribe(tmp_path / "test.wav", "audio/wav")
    primary, fallback = client.models.calls
    assert [primary["model"], fallback["model"]] == ["gemini-3.8-flash", "gemini-3.7-flash"]
    assert primary["contents"] is fallback["contents"]
    assert primary["config"] is fallback["config"]
    assert "segments" in fallback["config"].response_json_schema["properties"]
    assert fallback["config"].temperature is None
    assert result.model == "gemini-3.7-flash"
    assert any("primary transcription model was unavailable" in warning for warning in result.warnings)
    assert client.files.deleted == ["files/abc"]


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 504])
def test_non_recoverable_errors_do_not_switch_models(tmp_path, code):
    client = client_with(api_error(code, "ERROR", "private response"))
    with pytest.raises(TranscriptionError, match=f"HTTP {code}"):
        GeminiPromptedTranscriber(client).transcribe(tmp_path / "test.wav", "audio/wav")
    assert len(client.models.calls) == 1
    assert client.files.deleted == ["files/abc"]


@pytest.mark.parametrize("fallback", [None, "", "gemini-3.8-flash"])
def test_fallback_disabled_or_equal_does_not_repeat_generation(tmp_path, fallback):
    client = client_with(api_error(503, "UNAVAILABLE", "private response"))
    with pytest.raises(TranscriptionError):
        GeminiPromptedTranscriber(client, fallback_model=fallback).transcribe(tmp_path / "test.wav", "audio/wav")
    assert len(client.models.calls) == 1


def test_both_models_fail_with_safe_status_and_remote_cleanup(tmp_path, caplog):
    client = client_with(api_error(503, "UNAVAILABLE", "PRIVATE-KEY-AUDIO"),
                         api_error(500, "INTERNAL", "PRIVATE-KEY-AUDIO"))
    with pytest.raises(TranscriptionError) as info:
        GeminiPromptedTranscriber(client).transcribe(tmp_path / "test.wav", "audio/wav")
    message = info.value.user_message
    assert "model generation" in message and "HTTP 500" in message
    assert "gemini-3.8-flash, gemini-3.7-flash" in message
    assert "PRIVATE-KEY-AUDIO" not in message + caplog.text
    assert "HTTP 503" in caplog.text and "HTTP 500" in caplog.text
    assert client.files.deleted == ["files/abc"]


def test_files_api_failure_identifies_upload_and_never_tries_models(tmp_path):
    client = client_with()

    def fail_upload(**kwargs):
        raise api_error(503, "UNAVAILABLE", "private")

    client.files.upload = fail_upload
    with pytest.raises(TranscriptionError, match=r"audio upload/processing.*HTTP 503"):
        GeminiPromptedTranscriber(client).transcribe(tmp_path / "test.wav", "audio/wav")
    assert not client.models.calls


def test_asr_unavailable_keeps_asr_configuration_and_never_uses_flash(tmp_path):
    client = client_with(api_error(503, "UNAVAILABLE", "private"))
    with pytest.raises(TranscriptionError):
        GeminiASRTranscriber(client).transcribe(tmp_path / "test.wav", "audio/wav")
    assert len(client.models.calls) == 1
    assert client.models.calls[0]["model"] == "gemini-3.5-transcribe"
    assert client.models.calls[0]["config"].audio_transcription_config is not None
    assert client.files.deleted == ["files/abc"]


def test_report_fallback_preserves_schema_and_tracks_actual_model():
    client = client_with(api_error(503, "UNAVAILABLE", "private"), SimpleNamespace(text='{"report": "ok"}'))
    report = GeminiReportClient(client)
    schema = {"type": "object", "properties": {"report": {"type": "string"}}}
    assert report.generate_json("system", "prompt", schema) == '{"report": "ok"}'
    assert report.actual_model == "gemini-3.7-flash"
    assert client.models.calls[0]["config"] is client.models.calls[1]["config"]
    assert client.models.calls[1]["config"].response_json_schema == schema


def test_quota_error_on_fallback_is_reported_without_another_attempt():
    client = client_with(api_error(503, "UNAVAILABLE", "private"), api_error(429, "RESOURCE_EXHAUSTED", "private"))
    with pytest.raises(ReportGenerationError, match="rate limit.*HTTP 429"):
        GeminiReportClient(client).generate_json("system", "prompt", {})
    assert len(client.models.calls) == 2


def test_model_settings_read_secrets_env_priority_and_blank_fallback(monkeypatch):
    from ui import settings

    for name in ("GEMINI_TRANSCRIPTION_MODEL", "GEMINI_ASR_MODEL", "GEMINI_REPORT_MODEL", "GEMINI_FALLBACK_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings.st, "secrets", {
        "GEMINI_TRANSCRIPTION_MODEL": " gemini-3.7-flash ",
        "GEMINI_REPORT_MODEL": "gemini-3.7-flash", "GEMINI_FALLBACK_MODEL": "",
    })
    models = settings.app_models()
    assert models.prompted == models.report == "gemini-3.7-flash"
    assert models.fallback == ""
    monkeypatch.setenv("GEMINI_REPORT_MODEL", "gemini-3.8-flash")
    assert settings.app_models().report == "gemini-3.8-flash"


def test_pipeline_model_overrides_reach_both_shared_engines(monkeypatch):
    from pipeline import build_engines

    client = client_with()
    monkeypatch.setattr("pipeline.create_client", lambda key: client)
    models = GeminiModels(prompted="gemini-3.7-flash", asr="custom-asr", report="gemini-3.7-flash", fallback="")
    transcriber, reporter = build_engines("prompted", "test-key", models)
    assert transcriber._client is reporter._client is client
    assert transcriber._model == reporter._model == "gemini-3.7-flash"
    assert transcriber._fallback_model == reporter._fallback_model == ""
    asr, _ = build_engines("asr", "test-key", models)
    assert asr._model == "custom-asr"


@pytest.mark.parametrize("outcome", [SimpleNamespace(text="OK"), api_error(503, "UNAVAILABLE", "private")])
def test_connection_check_closes_client_and_does_not_fallback(monkeypatch, outcome):
    client = client_with(outcome)
    closed = []
    client.close = lambda: closed.append(True)
    monkeypatch.setattr("utils.gemini.create_client", lambda key: client)
    if isinstance(outcome, Exception):
        with pytest.raises(ConfigurationError, match="HTTP 503"):
            check_model_connection("test-key", "gemini-3.7-flash")
    else:
        check_model_connection("test-key", "gemini-3.7-flash")
    assert closed == [True]
    assert len(client.models.calls) == 1
    assert isinstance(client.models.calls[0]["contents"], str)
    assert client.files.deleted == []


def test_ui_connection_check_only_runs_on_click_and_shows_safe_error(monkeypatch):
    monkeypatch.setattr("ui.settings.app_api_key", lambda: "test-key")
    calls = []

    def check(key, model):
        calls.append(model)
        raise ConfigurationError("Connection test failed (HTTP 503)")

    monkeypatch.setattr("utils.gemini.check_model_connection", check)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    assert not app.exception and not calls
    app.button(key="check_gemini").click().run()
    assert not app.exception and len(calls) == 1
    assert any("HTTP 503" in error.value for error in app.error)
    app.run()
    assert len(calls) == 1
