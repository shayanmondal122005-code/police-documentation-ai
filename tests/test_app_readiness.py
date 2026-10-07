"""Regression checks for the interactive demo and cloud failure paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from errors import TranscriptionError

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
    assert app.text_input(key="police_station").value == ""
    assert app.text_input(key="district").value == ""
    assert app.text_input(key="officer_rank").value == ""


def test_professional_report_preview_and_station_details(monkeypatch):
    app = demo_app(monkeypatch)
    app.text_input(key="police_station").set_value("Sample Station")
    app.text_input(key="district").set_value("Sample District")
    app.text_input(key="officer_rank").set_value("Sub Inspector").run()
    app.button[0].click().run()
    report = app.session_state["result"].report
    assert report.admin.police_station == "Sample Station"
    assert report.admin.district == "Sample District"
    assert report.admin.officer_rank == "Sub Inspector"
    assert any("## 2. Incident Narrative" in block.value for block in app.markdown)
    assert any(expander.label == "Edit report text" for expander in app.expander)


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


def test_streamlit_secrets_key_used_without_environment_mutation(monkeypatch):
    from ui import settings

    monkeypatch.setattr(settings, "get_api_key", lambda: None)
    monkeypatch.setattr(settings.st, "secrets", {"GROQ_API_KEY": " test-key "})
    assert settings.app_api_key() == "test-key"


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
        run_pipeline(*demo_recording(), "groq", TranscriptionOptions(), ReportMetadata())
    assert closed == [True]
