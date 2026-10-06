"""Transcription parsing and plumbing, with the Gemini layer faked."""

import json
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from errors import NoSpeechError, TranscriptionError
from transcription.base import TranscriptionOptions, TranscriptResult, TranscriptSegment
from transcription.gemini_transcriber import (
    GeminiASRTranscriber,
    GeminiPromptedTranscriber,
    format_offset,
    parse_asr_response,
    parse_prompted_response,
)
from transcription.mock_transcriber import MockTranscriber
from utils.gemini import translate_error


def prompted_json(**overrides):
    data = {
        "segments": [
            {"speaker": "Speaker 1", "text": "हम काल्हु रात में करीब नौ बजे उहाँ गइल रहीं", "start_time": "00:03", "end_time": "00:09"}
        ],
        "language_notes": "Bhojpuri with Hindi",
        "uncertainties": ["one word unclear"],
        "no_speech_detected": False,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def asr_response(parts):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=parts))])


def asr_part(text, speaker=None, words=None, lang="hi-IN"):
    return types.Part(
        audio_transcription=types.Transcription(
            text=text,
            speaker_label=speaker,
            language_code=lang,
            words=[types.WordInfo(word=w, start_offset=s, end_offset=e) for w, s, e in (words or [])],
        )
    )


# ----------------------------------------------------------- prompted engine


def test_prompted_response_preserves_bhojpuri_text_verbatim():
    result = parse_prompted_response(prompted_json(), "gemini-3.8-flash")
    assert result.raw_transcript == "हम काल्हु रात में करीब नौ बजे उहाँ गइल रहीं"
    assert result.language_notes == "Bhojpuri with Hindi"
    assert result.timestamp_source == "model_reported"
    assert result.uncertainties == ["one word unclear"]
    assert any("unverified" in w for w in result.warnings)


def test_prompted_no_speech_raises():
    with pytest.raises(NoSpeechError):
        parse_prompted_response(prompted_json(segments=[], no_speech_detected=True), "m")
    with pytest.raises(NoSpeechError):
        parse_prompted_response(prompted_json(segments=[{"text": "   "}]), "m")


def test_prompted_malformed_json_raises_controlled_error():
    with pytest.raises(TranscriptionError) as info:
        parse_prompted_response("not json at all", "m")
    assert "could not be validated" in info.value.user_message


def test_prompted_garbage_times_are_dropped_not_kept():
    result = parse_prompted_response(
        prompted_json(segments=[{"speaker": None, "text": "x", "start_time": "around noon", "end_time": "later"}]), "m"
    )
    assert result.segments[0].start_time is None and result.segments[0].end_time is None
    assert result.timestamp_source == "none"  # nothing real remains, so no claim is made
    assert result.speakers_available is False


def test_result_never_claims_unavailable_capabilities():
    result = TranscriptResult(
        raw_transcript="x",
        segments=[TranscriptSegment(text="x")],
        timestamp_source="asr_word_offsets",
        speakers_available=True,
    )
    assert result.timestamp_source == "none" and result.speakers_available is False
    assert result.to_analysis_text() == "[1] x"


def test_analysis_text_includes_only_real_metadata():
    result = TranscriptResult(
        raw_transcript="a\nb",
        segments=[
            TranscriptSegment(speaker="Speaker 1", text="a", start_time="00:01", end_time="00:02"),
            TranscriptSegment(text="b"),
        ],
        timestamp_source="model_reported",
    )
    assert result.to_analysis_text() == "[1] [00:01–00:02] Speaker 1: a\n[2] b"


class FakeFiles:
    def __init__(self):
        self.deleted = []

    def upload(self, file, config=None):
        return SimpleNamespace(name="files/abc", state=SimpleNamespace(name="ACTIVE"), uri="u", mime_type=config.mime_type)

    def get(self, name):
        raise AssertionError("not expected for ACTIVE files")

    def delete(self, name):
        self.deleted.append(name)


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def fake_client(response=None, error=None):
    return SimpleNamespace(files=FakeFiles(), models=FakeModels(response, error))


def test_prompted_transcriber_sends_prompt_and_schema_and_deletes_remote_file(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    client = fake_client(SimpleNamespace(text=prompted_json()))
    result = GeminiPromptedTranscriber(client=client, model="gemini-3.8-flash").transcribe(audio, "audio/wav")
    sent = client.models.kwargs
    assert sent["model"] == "gemini-3.8-flash"
    assert "Bhojpuri" in sent["config"].system_instruction
    assert sent["config"].response_mime_type == "application/json"
    assert "segments" in sent["config"].response_json_schema["properties"]
    assert client.files.deleted == ["files/abc"]
    assert result.engine == "prompted"


def test_remote_file_is_deleted_even_when_generation_fails(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    client = fake_client(error=ConnectionError("boom"))
    with pytest.raises(TranscriptionError) as info:
        GeminiPromptedTranscriber(client=client).transcribe(audio, "audio/wav")
    assert client.files.deleted == ["files/abc"]
    assert "network" in info.value.user_message


# ----------------------------------------------------------- ASR engine


def test_format_offset():
    assert format_offset("12.5s") == "00:12.5"
    assert format_offset("75s") == "01:15.0"
    assert format_offset("garbage") is None and format_offset(None) is None


def test_asr_response_maps_speakers_and_word_offsets():
    response = asr_response(
        [
            asr_part("आप कौन हैं", "spk_1", [("आप", "0.5s", "0.9s"), ("हैं", "1.2s", "2.0s")]),
            asr_part("मैं सुनील हूँ", "spk_2", [("मैं", "3s", "3.4s"), ("हूँ", "4s", "5.5s")]),
        ]
    )
    result = parse_asr_response(response, "gemini-3.5-transcribe", with_timestamps=True, with_speakers=True)
    assert result.raw_transcript == "आप कौन हैं\nमैं सुनील हूँ"
    assert [s.speaker for s in result.segments] == ["spk_1", "spk_2"]
    assert (result.segments[0].start_time, result.segments[0].end_time) == ("00:00.5", "00:02.0")
    assert result.timestamp_source == "asr_word_offsets" and result.speakers_available
    assert any("Bhojpuri" in w for w in result.warnings)


def test_asr_without_annotations_falls_back_to_plain_text_without_inventing_metadata():
    response = SimpleNamespace(candidates=[], text="सिर्फ टेक्स्ट")
    result = parse_asr_response(response, "m", with_timestamps=True, with_speakers=True)
    assert result.raw_transcript == "सिर्फ टेक्स्ट"
    assert result.timestamp_source == "none" and result.speakers_available is False


def test_asr_empty_response_is_no_speech():
    with pytest.raises(NoSpeechError):
        parse_asr_response(SimpleNamespace(candidates=[], text=""), "m", True, True)


def test_asr_transcriber_requests_diarization_and_timestamps(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3")
    client = fake_client(asr_response([asr_part("नमस्ते", "spk_1", [("नमस्ते", "0s", "1s")])]))
    GeminiASRTranscriber(client=client).transcribe(
        audio, "audio/mp3", TranscriptionOptions(with_timestamps=True, with_speakers=True)
    )
    config = client.models.kwargs["config"].audio_transcription_config
    assert config.diarization is True and config.word_timestamp is True
    assert config.mode == types.AudioTranscriptionConfigMode.VERBATIM
    assert client.models.kwargs["model"] == "gemini-3.5-transcribe"


# ----------------------------------------------------------- mock + errors


def test_mock_transcriber_needs_no_audio_or_key(tmp_path):
    result = MockTranscriber().transcribe(tmp_path / "missing.wav", "audio/wav")
    assert result.engine == "mock" and result.raw_transcript
    assert any("MOCK" in w for w in result.warnings)


def api_error(code, status, message):
    return genai_errors.APIError(code, {"error": {"code": code, "status": status, "message": message}})


@pytest.mark.parametrize(
    "exc, expected",
    [
        (api_error(429, "RESOURCE_EXHAUSTED", "RAW-DETAIL-XYZ"), "rate limit"),
        (api_error(400, "INVALID_ARGUMENT", "API key not valid"), "API key was rejected"),
        (api_error(403, "PERMISSION_DENIED", "denied"), "API key was rejected"),
        (api_error(400, "INVALID_ARGUMENT", "bad media"), "corrupted"),
        (api_error(503, "UNAVAILABLE", "overloaded"), "temporarily unavailable"),
        (api_error(504, "DEADLINE_EXCEEDED", "slow"), "timed out"),
        (TimeoutError(), "timed out"),
        (ConnectionError(), "network"),
        (RuntimeError("secret internals"), "unexpectedly"),
    ],
)
def test_gemini_errors_become_safe_messages(exc, expected):
    message = translate_error(exc, TranscriptionError, "Transcription").user_message
    assert expected in message
    assert "secret internals" not in message and "RAW-DETAIL-XYZ" not in message
