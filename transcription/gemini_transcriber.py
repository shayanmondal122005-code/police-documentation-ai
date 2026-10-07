"""Gemini transcription engines.

Two engines share the `Transcriber` interface:

* `GeminiPromptedTranscriber` - an instruction-following Gemini model with the
  Hindi/Bhojpuri prompt. Speaker labels and times are model-reported text.
* `GeminiASRTranscriber` - the dedicated `gemini-3.5-transcribe` ASR model, which can
  return diarization and word offsets, but accepts no instructions.
"""

from __future__ import annotations

import re
import math
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from config import (
    ASR_TRANSCRIPTION_MODEL,
    ENGINE_ASR,
    ENGINE_PROMPTED,
    FALLBACK_MODEL,
    PROMPTED_TRANSCRIPTION_MODEL,
)
from errors import NoSpeechError, TranscriptionError
from prompts.transcription_prompt import TRANSCRIPTION_SYSTEM_INSTRUCTION, TRANSCRIPTION_USER_PROMPT
from transcription.base import (
    Transcriber,
    TranscriptionOptions,
    TranscriptResult,
    TranscriptSegment,
)
from utils.gemini import create_client, generate_with_fallback, simplify_schema, translate_error, uploaded_audio

_TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_ACTION = "Transcription"


# ---------------------------------------------------------------- prompted engine


class _PromptedSegment(BaseModel):
    speaker: str | None = None
    text: str
    start_time: str | None = None
    end_time: str | None = None
    language: str | None = None


class _PromptedTranscript(BaseModel):
    """Schema the prompted model must return."""

    segments: list[_PromptedSegment] = Field(default_factory=list)
    language_notes: str | None = None
    uncertainties: list[str] = Field(default_factory=list)
    no_speech_detected: bool = False


def _clean_time(value: str | None) -> str | None:
    """Keep only well-formed MM:SS / H:MM:SS strings; anything else becomes None."""
    if value and _TIME_PATTERN.match(value.strip()):
        return value.strip()
    return None


def parse_prompted_response(response_text: str, model: str) -> TranscriptResult:
    """Validate the prompted model's JSON and convert it into a TranscriptResult."""
    try:
        parsed = _PromptedTranscript.model_validate_json(response_text)
    except (ValidationError, ValueError) as exc:
        raise TranscriptionError(
            "The transcription model returned a response that could not be validated. Please try again."
        ) from exc
    segments = [
        TranscriptSegment(
            speaker=(s.speaker or None),
            text=s.text.strip(),
            start_time=_clean_time(s.start_time),
            end_time=_clean_time(s.end_time),
            language=s.language,
        )
        for s in parsed.segments
        if s.text.strip()
    ]
    if parsed.no_speech_detected or not segments:
        raise NoSpeechError("No intelligible speech was detected in this recording.")
    return TranscriptResult(
        raw_transcript="\n".join(s.text for s in segments),
        segments=segments,
        language_notes=parsed.language_notes,
        uncertainties=parsed.uncertainties,
        timestamp_source="model_reported",
        speakers_available=True,
        engine=ENGINE_PROMPTED,
        model=model,
        warnings=[
            "Speaker labels and times come from a general-purpose model, not an aligned ASR "
            "system. They are model-reported and unverified."
        ],
    )


class GeminiPromptedTranscriber(Transcriber):
    """Transcribe with an instruction-following Gemini model and the Hindi/Bhojpuri prompt."""

    name = ENGINE_PROMPTED

    def __init__(self, client: genai.Client | None = None, model: str = PROMPTED_TRANSCRIPTION_MODEL,
                 fallback_model: str | None = FALLBACK_MODEL) -> None:
        self._client = client
        self._model = model
        self._fallback_model = fallback_model

    def transcribe(
        self, audio_path: Path, mime_type: str, options: TranscriptionOptions | None = None
    ) -> TranscriptResult:
        try:
            client = self._client or create_client()
            with uploaded_audio(client, audio_path, mime_type) as audio_file:
                response, actual_model = generate_with_fallback(
                    client,
                    model=self._model,
                    fallback_model=self._fallback_model,
                    error_cls=TranscriptionError,
                    action=_ACTION,
                    contents=[TRANSCRIPTION_USER_PROMPT, audio_file],
                    config=types.GenerateContentConfig(
                        system_instruction=TRANSCRIPTION_SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_json_schema=simplify_schema(_PromptedTranscript.model_json_schema()),
                    ),
                )
            result = parse_prompted_response(response.text or "", actual_model)
            if actual_model != self._model:
                result.warnings.append(f"The primary transcription model was unavailable; {actual_model} produced this transcript.")
            return result
        except (NoSpeechError, TranscriptionError):
            raise
        except Exception as exc:  # noqa: BLE001 - translated to a safe message
            raise translate_error(exc, TranscriptionError, "Transcription (audio upload/processing)") from exc


# ---------------------------------------------------------------- dedicated ASR engine


def format_offset(offset: str | None) -> str | None:
    """Convert a duration string like '12.5s' to 'MM:SS.s'; None if it cannot be parsed."""
    if not offset:
        return None
    try:
        seconds = float(str(offset).strip().rstrip("s"))
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes):02d}:{secs:04.1f}"


def _segment_from_part(part: Any) -> TranscriptSegment | None:
    transcription = getattr(part, "audio_transcription", None)
    if transcription is None:
        return None
    words = getattr(transcription, "words", None) or []
    text = (getattr(transcription, "text", None) or "").strip()
    if not text:
        text = " ".join((getattr(word, "word", None) or "").strip() for word in words).strip()
    if not text:
        return None
    return TranscriptSegment(
        speaker=getattr(transcription, "speaker_label", None) or None,
        text=text,
        start_time=format_offset(words[0].start_offset) if words else None,
        end_time=format_offset(words[-1].end_offset) if words else None,
        language=getattr(transcription, "language_code", None),
    )


def parse_asr_response(response: Any, model: str, with_timestamps: bool, with_speakers: bool) -> TranscriptResult:
    """Convert a `gemini-3.5-transcribe` response into a TranscriptResult.

    Uses per-part `audio_transcription` annotations when present; otherwise falls back
    to the plain response text with no speaker or time information.
    """
    parts = []
    for candidate in getattr(response, "candidates", None) or []:
        parts.extend(getattr(getattr(candidate, "content", None), "parts", None) or [])
    segments = [seg for seg in (_segment_from_part(p) for p in parts) if seg]
    for segment in segments:
        if not with_timestamps:
            segment.start_time = segment.end_time = None
        if not with_speakers:
            segment.speaker = None

    if segments:
        raw = "\n".join(s.text for s in segments)
    else:
        raw = (getattr(response, "text", None) or "").strip()
        if raw:
            segments = [TranscriptSegment(text=raw)]
    if not raw:
        raise NoSpeechError("No intelligible speech was detected in this recording.")

    languages = sorted({s.language for s in segments if s.language})
    return TranscriptResult(
        raw_transcript=raw,
        segments=segments,
        language_notes=("Languages detected by the ASR model: " + ", ".join(languages)) if languages else None,
        uncertainties=[],
        timestamp_source="asr_word_offsets" if with_timestamps else "none",
        speakers_available=with_speakers,
        engine=ENGINE_ASR,
        model=model,
        warnings=[
            "Bhojpuri is not in the documented language list of this model; Bhojpuri speech may be "
            "rendered as Hindi-like text. This engine accepts no instructions, so the "
            "Hindi/Bhojpuri preservation prompt was not applied.",
            "ASR confidence is not exposed; unclear passages are not marked automatically.",
        ],
    )


class GeminiASRTranscriber(Transcriber):
    """Transcribe with the dedicated `gemini-3.5-transcribe` speech-to-text model."""

    name = ENGINE_ASR

    def __init__(self, client: genai.Client | None = None, model: str = ASR_TRANSCRIPTION_MODEL) -> None:
        self._client = client
        self._model = model

    def transcribe(
        self, audio_path: Path, mime_type: str, options: TranscriptionOptions | None = None
    ) -> TranscriptResult:
        options = options or TranscriptionOptions()
        asr_config = types.AudioTranscriptionConfig(
            diarization=options.with_speakers,
            word_timestamp=options.with_timestamps,
            mode=types.AudioTranscriptionConfigMode.VERBATIM,
        )
        try:
            client = self._client or create_client()
            with uploaded_audio(client, audio_path, mime_type) as audio_file:
                response, _ = generate_with_fallback(
                    client,
                    model=self._model,
                    error_cls=TranscriptionError,
                    action=_ACTION,
                    contents=[audio_file],
                    config=types.GenerateContentConfig(audio_transcription_config=asr_config),
                )
            return parse_asr_response(response, self._model, options.with_timestamps, options.with_speakers)
        except (NoSpeechError, TranscriptionError):
            raise
        except Exception as exc:  # noqa: BLE001 - translated to a safe message
            raise translate_error(exc, TranscriptionError, "Transcription (audio upload/processing)") from exc
