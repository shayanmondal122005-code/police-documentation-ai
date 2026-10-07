"""Exercise the real Groq SDK against an in-memory HTTP transport, never a live API."""

import copy
import json
from types import SimpleNamespace

import groq
import httpx
import pytest
from streamlit.testing.v1 import AppTest

from config import MAX_UPLOAD_BYTES, GroqModels
from documentation.clients import GroqReportClient
from documentation.schemas import ModelReport
from errors import ConfigurationError, FileTooLargeError, ReportGenerationError, TranscriptionError
from pipeline import ReportMetadata, demo_recording, run_pipeline
from tests.test_app_readiness import ROOT
from tests.test_transcription import whisper_response
from transcription.base import TranscriptionOptions
from transcription.groq_transcriber import GroqWhisperTranscriber
from utils.audio import validate_upload
from utils.groq import check_model_connection, strict_schema, translate_error


def completion(content, finish="stop", refusal=None):
    return {"id": "test", "object": "chat.completion", "created": 1, "model": "openai/gpt-oss-120b",
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": content, "refusal": refusal}}]}


def sdk_client(handler, retries=0):
    return groq.Groq(api_key="gsk-TEST-ONLY", max_retries=retries,
                     http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_real_sdk_pipeline_uses_groq_for_both_stages(monkeypatch, mock_analysis_json):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "api.groq.com"
        if request.url.path.endswith("/audio/transcriptions"):
            body = request.content
            assert b"RIFF" in body and b"whisper-large-v3" in body
            assert b"verbose_json" in body and b"segment" in body
            assert b'filename="recording.wav"' in body
            assert b'name="language"' not in body  # preserve language detection for mixtures
            return httpx.Response(200, json=whisper_response())
        assert request.url.path.endswith("/chat/completions")
        sent = json.loads(request.content)
        assert sent["model"] == "openai/gpt-oss-120b"
        assert sent["response_format"]["json_schema"]["strict"] is True
        assert sent["max_completion_tokens"] == 4096
        assert sent["reasoning_effort"] == "low"
        assert whisper_response()["text"] in sent["messages"][1]["content"]
        return httpx.Response(200, json=completion(mock_analysis_json))

    client = sdk_client(handler)
    monkeypatch.setattr("pipeline.create_client", lambda key: client)
    result = run_pipeline(*demo_recording(), "groq", TranscriptionOptions(), ReportMetadata(officer="Reviewer"), api_key="test")
    assert len(requests) == 2
    assert client.is_closed()
    assert result.transcript.raw_transcript == whisper_response()["text"]
    assert result.transcript.timestamp_source == "asr_segment_offsets"
    assert not result.report.transcript_meta.speakers_available
    assert result.report_model == "openai/gpt-oss-120b"
    assert result.report.admin.officer == "Reviewer"
    assert "AI-GENERATED DRAFT" in result.markdown
    assert "gsk-TEST-ONLY" not in result.markdown


def test_strict_schema_closes_every_object_and_preserves_nullable_fields():
    original = ModelReport.model_json_schema()
    before = copy.deepcopy(original)
    schema = strict_schema(original)

    def inspect(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for child in node.values():
                inspect(child)
        elif isinstance(node, list):
            for child in node:
                inspect(child)

    inspect(schema)
    assert original == before
    assert {"type": "null"} in schema["$defs"]["SourceRef"]["properties"]["start_time"]["anyOf"]
    field_schema = strict_schema({"type": "object", "properties": {"title": {"type": "string", "title": "Label"}}})
    assert "title" in field_schema["properties"]
    assert "title" not in field_schema["properties"]["title"]


@pytest.mark.parametrize("code,expected", [(401, "key was rejected"), (403, "permissions"), (404, "unavailable"),
                                          (413, "too large"), (429, "rate limit"), (503, "temporarily unavailable"), (400, "rejected")])
def test_http_errors_are_safe_with_exact_status(code, expected, caplog):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions")
    exc = groq.APIStatusError("PRIVATE-KEY-AUDIO", response=httpx.Response(code, request=request), body={"error": "PRIVATE-KEY-AUDIO"})
    message = translate_error(exc, TranscriptionError, "Groq transcription").user_message
    assert expected in message and f"HTTP {code}" in message
    assert "PRIVATE-KEY-AUDIO" not in message + caplog.text


def test_sdk_retries_transient_error_then_succeeds_and_file_closes(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.content)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"message": "private"}}, headers={"retry-after-ms": "1"})
        return httpx.Response(200, json=whisper_response())

    path = tmp_path / "sample.wav"
    path.write_bytes(b"RIFFtest")
    client = sdk_client(handler, retries=2)
    result = GroqWhisperTranscriber(client).transcribe(path, "audio/wav")
    assert len(calls) == 2 and all(b"RIFFtest" in body for body in calls)
    assert result.engine == "groq"
    client.close()


@pytest.mark.parametrize("with_timestamps", [True, False])
def test_upload_handle_is_closed_when_transcription_fails(tmp_path, with_timestamps):
    captured = []

    def fail(**kwargs):
        captured.append(kwargs)
        raise ConnectionError("PRIVATE-KEY")

    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=fail)))
    path = tmp_path / "sample.wav"
    path.write_bytes(b"RIFFtest")
    with pytest.raises(TranscriptionError, match="connection"):
        GroqWhisperTranscriber(client).transcribe(path, "audio/wav", TranscriptionOptions(with_timestamps=with_timestamps))
    assert captured[0]["file"][1].closed
    assert ("timestamp_granularities" in captured[0]) is with_timestamps


@pytest.mark.parametrize("finish,content,refusal,expected", [
    ("length", '{"partial": 1}', None, "output limit"),
    ("content_filter", "", None, "declined"),
    ("stop", "", None, "no report text"),
    ("stop", "{}", "PRIVATE-REFUSAL", "declined"),
])
def test_partial_empty_and_refused_reports_are_not_accepted(finish, content, refusal, expected):
    with sdk_client(lambda request: httpx.Response(200, json=completion(content, finish, refusal))) as client:
        with pytest.raises(ReportGenerationError, match=expected):
            GroqReportClient(client).generate_json("system", "prompt", ModelReport.model_json_schema())


def test_oversize_recording_rejected_before_any_cloud_call(monkeypatch):
    assert validate_upload("a.wav", MAX_UPLOAD_BYTES)
    with pytest.raises(FileTooLargeError):
        validate_upload("a.wav", MAX_UPLOAD_BYTES + 1)
    monkeypatch.setattr("utils.audio.MAX_UPLOAD_BYTES", 3)
    monkeypatch.setattr("pipeline.build_engines", lambda *args: pytest.fail("No cloud call for oversized audio"))
    with pytest.raises(FileTooLargeError):
        run_pipeline("a.wav", b"1234", "groq", TranscriptionOptions(), ReportMetadata())


def test_secrets_model_overrides_and_env_priority(monkeypatch):
    from ui import settings

    monkeypatch.delenv("GROQ_TRANSCRIPTION_MODEL", raising=False)
    monkeypatch.delenv("GROQ_REPORT_MODEL", raising=False)
    monkeypatch.setattr(settings.st, "secrets", {"GROQ_TRANSCRIPTION_MODEL": " whisper-large-v3-turbo ",
                                                "GROQ_REPORT_MODEL": "openai/gpt-oss-20b"})
    assert settings.app_models() == GroqModels(transcription="whisper-large-v3-turbo", report="openai/gpt-oss-20b")
    monkeypatch.setenv("GROQ_REPORT_MODEL", "openai/gpt-oss-120b")
    assert settings.app_models().report == "openai/gpt-oss-120b"


def test_invalid_model_rejected_before_client_creation(monkeypatch):
    from pipeline import build_engines

    monkeypatch.setattr("pipeline.create_client", lambda *args: pytest.fail("Do not create client for an incompatible model"))
    with pytest.raises(ConfigurationError, match="strict structured"):
        build_engines("groq", "test", GroqModels(report="gemini-old-model"))


def test_gemini_key_does_not_enable_groq(monkeypatch):
    from ui import settings

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "old-key")
    monkeypatch.setattr(settings.st, "secrets", {"GEMINI_API_KEY": "old-key"})
    assert settings.app_api_key() is None


def test_connection_check_uses_strict_json_and_closes_client(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=completion('{"ok":true}'))

    client = sdk_client(handler)
    monkeypatch.setattr("utils.groq.create_client", lambda key: client)
    check_model_connection("test", GroqModels())
    assert len(requests) == 1 and client.is_closed()
    assert requests[0].url.path.endswith("/chat/completions")
    assert json.loads(requests[0].content)["response_format"]["json_schema"]["strict"] is True


def test_ui_connection_check_only_runs_on_click_and_has_no_speaker_option(monkeypatch):
    monkeypatch.setattr("ui.settings.app_api_key", lambda: "test-key")
    calls = []

    def check(key, models):
        calls.append(models)
        raise ConfigurationError("Groq connection failed (HTTP 429)")

    monkeypatch.setattr("utils.groq.check_model_connection", check)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    assert not app.exception and not calls
    assert app.selectbox(key="engine").options == ["Groq Whisper — multilingual transcription", "Mock — local demo transcript (no API key, no audio sent)"]
    assert all("Speaker" not in checkbox.label for checkbox in app.checkbox)
    app.button(key="check_groq").click().run()
    assert not app.exception and len(calls) == 1
    assert any("HTTP 429" in error.value for error in app.error)
    app.run()
    assert len(calls) == 1
