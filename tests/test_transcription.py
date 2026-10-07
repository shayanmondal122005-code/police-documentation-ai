"""Groq Whisper parsing and engine-independent transcript guarantees."""

from types import SimpleNamespace

import pytest

from errors import NoSpeechError, TranscriptionError
from transcription.base import TranscriptResult, TranscriptSegment
from transcription.groq_transcriber import format_offset, parse_whisper_response
from transcription.mock_transcriber import MockTranscriber


def whisper_response(**overrides):
    result = {
        "text": "हम काल्हु रात में करीब नौ बजे उहाँ गइल रहीं",
        "language": "hindi",
        "segments": [{"text": "हम काल्हु रात में करीब नौ बजे उहाँ गइल रहीं", "start": 3.0, "end": 9.2}],
    }
    result.update(overrides)
    return result


@pytest.mark.parametrize("as_object", [False, True])
def test_whisper_preserves_raw_text_and_provider_segment_offsets(as_object):
    response = whisper_response()
    result = parse_whisper_response(SimpleNamespace(**response) if as_object else response, "whisper-large-v3")
    assert result.raw_transcript == response["text"]
    assert result.timestamp_source == "asr_segment_offsets"
    assert result.segments[0].start_time == "00:03.0"
    assert result.segments[0].end_time == "00:09.2"
    assert result.segments[0].speaker is None and not result.speakers_available
    assert result.engine == "groq" and result.model == "whisper-large-v3"
    assert any("Bhojpuri" in warning for warning in result.warnings)


@pytest.mark.parametrize("value", [None, -2, float("nan"), float("inf"), "garbage", True, {}])
def test_bad_offsets_do_not_create_timestamps(value):
    assert format_offset(value) is None


def test_rounding_offsets_does_not_produce_sixty_seconds():
    assert format_offset(59.99) == "01:00.0"
    assert format_offset(75) == "01:15.0"


@pytest.mark.parametrize("start,end", [(10, 2), (-1, 2), (None, 2), (1, float("inf"))])
def test_bad_segment_times_are_dropped(start, end):
    response = whisper_response()
    response["segments"][0].update(start=start, end=end)
    result = parse_whisper_response(response, "whisper-large-v3")
    assert result.segments[0].start_time is None and result.segments[0].end_time is None
    assert result.timestamp_source == "none"


def test_disabled_timestamps_leave_no_time_claims():
    result = parse_whisper_response(whisper_response(), "whisper-large-v3", False)
    assert result.timestamp_source == "none"
    assert result.segments[0].start_time is None


def test_incomplete_segment_text_cannot_replace_full_raw_transcript():
    response = whisper_response(segments=[{"text": "हम काल्हु", "start": 3, "end": 4}])
    result = parse_whisper_response(response, "whisper-large-v3")
    assert response["text"] in result.to_analysis_text()
    assert result.timestamp_source == "none"
    assert any("did not match" in warning for warning in result.warnings)


def test_plain_transcript_has_no_fabricated_speaker_or_time():
    result = parse_whisper_response({"text": "नमस्ते"}, "whisper-large-v3")
    assert result.raw_transcript == "नमस्ते"
    assert result.timestamp_source == "none" and not result.speakers_available


def test_low_confidence_flag_keeps_spoken_text_unchanged():
    response = whisper_response()
    response["segments"][0]["avg_logprob"] = -1.2
    result = parse_whisper_response(response, "whisper-large-v3")
    assert result.raw_transcript == response["text"]
    assert len(result.uncertainties) == 1


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_transcript_is_no_speech(text):
    with pytest.raises(NoSpeechError):
        parse_whisper_response({"text": text}, "whisper-large-v3")


def test_invalid_response_is_controlled_error():
    with pytest.raises(TranscriptionError):
        parse_whisper_response({"text": []}, "whisper-large-v3")


def test_result_never_claims_unavailable_capabilities():
    result = TranscriptResult(raw_transcript="x", segments=[TranscriptSegment(text="x")],
                              timestamp_source="asr_segment_offsets", speakers_available=True)
    assert result.timestamp_source == "none" and not result.speakers_available
    assert result.to_analysis_text() == "[1] x"


def test_analysis_text_includes_only_real_metadata():
    result = TranscriptResult(raw_transcript="a\nb", segments=[
        TranscriptSegment(speaker="Speaker 1", text="a", start_time="00:01", end_time="00:02"),
        TranscriptSegment(text="b"),
    ], timestamp_source="model_reported")
    assert result.to_analysis_text() == "[1] [00:01–00:02] Speaker 1: a\n[2] b"


def test_mock_transcriber_needs_no_audio_or_key(tmp_path):
    result = MockTranscriber().transcribe(tmp_path / "missing.wav", "audio/wav")
    assert result.engine == "mock" and result.raw_transcript
    assert any("MOCK" in warning for warning in result.warnings)
