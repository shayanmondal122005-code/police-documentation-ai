"""Regression checks for the interactive demo and cloud failure paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from errors import TranscriptionError
from transcription.gemini_transcriber import format_offset, parse_asr_response
from utils.gemini import upload_audio
from tests.test_transcription import asr_part, asr_response

ROOT = Path(__file__).resolve().parent.parent


def demo_app(monkeypatch):
    monkeypatch.setattr("ui.settings.get_api_key", lambda: None)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    app.radio(key="source").set_value("Try fictional demo").run()
    app.button[0].click().run()
    assert not app.exception
    return app


def test_demo_review_downloads_and_reset(monkeypatch):
    app = demo_app(monkeypatch)
    assert app.session_state["result"].transcript.engine == "mock"
    assert len(app.tabs) == 6
    assert all(d.proto.disabled for d in app.get("download_button") if d.label != "Download transcript.txt")
    app.checkbox(key="review_confirmed").check().run()
    downloads = {d.label: d.proto.disabled for d in app.get("download_button")}
    assert downloads["Word (.docx)"] is False
    assert downloads["Markdown (.md)"] is False
    app.text_area(key="officer_review").set_value("Correction after listening.").run()
    assert app.checkbox(key="review_confirmed").value is False
    app.button[-1].click().run()
    assert not app.exception
    assert "result" not in app.session_state
    assert app.text_input(key="officer").value == ""


def test_failed_generation_preserves_previous_report_and_edits(monkeypatch):
    app = demo_app(monkeypatch)
    app.text_area(key="report_text").set_value("Reviewed text to preserve").run()
    result = app.session_state["result"]

    def fail(*args, **kwargs):
        raise TranscriptionError("Temporary network failure")

    monkeypatch.setattr("pipeline.run_pipeline", fail)
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["result"] == result
    assert app.text_area(key="report_text").value == "Reviewed text to preserve"
    assert any("Temporary network failure" in error.value for error in app.error)


@pytest.mark.parametrize("state", ["FAILED", "PROCESSING"])
def test_remote_upload_cleaned_when_processing_fails(monkeypatch, tmp_path, state):
    deleted = []
    uploaded = SimpleNamespace(name="files/sample", state=state)
    files = SimpleNamespace(upload=lambda **kwargs: uploaded, delete=lambda **kwargs: deleted.append(kwargs["name"]))
    monkeypatch.setattr("utils.gemini.FILE_PROCESSING_TIMEOUT_SECONDS", -1)
    with pytest.raises((ValueError, TimeoutError)):
        upload_audio(SimpleNamespace(files=files), tmp_path / "test.wav", "audio/wav")
    assert deleted == ["files/sample"]


def test_asr_word_annotations_without_text_are_not_lost():
    response = asr_response([asr_part(None, "spk_1", [("नमस्ते", "0s", "1s"), ("जी", "1s", "2s")])])
    result = parse_asr_response(response, "m", True, True)
    assert result.raw_transcript == "नमस्ते जी"
    assert result.segments[0].end_time == "00:02.0"


def test_asr_respects_disabled_metadata_options():
    response = asr_response([asr_part("नमस्ते", "spk_1", [("नमस्ते", "0s", "1s")])])
    result = parse_asr_response(response, "m", False, False)
    assert result.segments[0].speaker is None
    assert result.segments[0].start_time is None
    assert result.timestamp_source == "none"


@pytest.mark.parametrize("offset", ["-2s", "nans", "infs"])
def test_invalid_word_offsets_do_not_break_transcription(offset):
    assert format_offset(offset) is None


def test_streamlit_secrets_key_used_without_environment_mutation(monkeypatch):
    from ui import settings

    monkeypatch.setattr(settings, "get_api_key", lambda: None)
    monkeypatch.setattr(settings.st, "secrets", {"GEMINI_API_KEY": " test-key "})
    assert settings.app_api_key() == "test-key"


def test_long_asr_recording_rejected_before_any_cloud_call(monkeypatch):
    from pipeline import ReportMetadata, demo_recording, run_pipeline
    from transcription.base import TranscriptionOptions
    from errors import ConfigurationError

    monkeypatch.setattr("pipeline.detect_duration_seconds", lambda *args: 1801)

    def no_cloud_calls(*args, **kwargs):
        pytest.fail("An over-limit request must not create a cloud client")

    monkeypatch.setattr("pipeline.build_engines", no_cloud_calls)
    with pytest.raises(ConfigurationError, match="30-minute"):
        run_pipeline(*demo_recording(), "asr", TranscriptionOptions(), ReportMetadata())


def test_request_client_closed_when_report_generation_fails(monkeypatch, mock_transcript):
    from pipeline import ReportMetadata, demo_recording, run_pipeline
    from transcription.base import TranscriptionOptions
    from errors import ReportGenerationError

    closed = []
    client = SimpleNamespace(close=lambda: closed.append(True))
    transcriber = SimpleNamespace(transcribe=lambda *args: mock_transcript)

    def fail(*args, **kwargs):
        raise ReportGenerationError("Service unavailable")

    report_client = SimpleNamespace(_client=client, generate_json=fail)
    monkeypatch.setattr("pipeline.build_engines", lambda *args: (transcriber, report_client))
    with pytest.raises(ReportGenerationError):
        run_pipeline(*demo_recording(), "prompted", TranscriptionOptions(), ReportMetadata())
    assert closed == [True]
