"""Groq Whisper transcription with real segment offsets and no invented speakers."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import groq

from config import ENGINE_GROQ, TRANSCRIPTION_MODEL
from errors import NoSpeechError, TranscriptionError
from prompts.transcription_prompt import WHISPER_CONTEXT_PROMPT
from transcription.base import Transcriber, TranscriptionOptions, TranscriptResult, TranscriptSegment
from utils.groq import close_client, create_client, translate_error


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _seconds(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def format_offset(value: Any) -> str | None:
    seconds = _seconds(value)
    if seconds is None:
        return None
    minutes, tenths = divmod(round(seconds * 10), 600)
    return f"{minutes:02d}:{tenths / 10:04.1f}"


def parse_whisper_response(response: Any, model: str, with_timestamps: bool = True) -> TranscriptResult:
    raw = _field(response, "text", "")
    if not isinstance(raw, str):
        raise TranscriptionError("Groq returned an invalid transcription response. Please try again.")
    raw = raw.strip()
    if not raw:
        raise NoSpeechError("No intelligible speech was detected in this recording.")
    language = _field(response, "language")
    segments: list[TranscriptSegment] = []
    uncertainties: list[str] = []
    warnings = [
        "Whisper does not provide speaker labels. Speaker attribution must be checked against the recording.",
        "Bhojpuri and mixed-language accuracy have not been measured; verify names, numbers and dialect wording.",
    ]
    for item in _field(response, "segments", []) or []:
        text = _field(item, "text", "")
        if not isinstance(text, str) or not text.strip():
            continue
        start, end = _seconds(_field(item, "start")), _seconds(_field(item, "end"))
        valid_times = start is not None and end is not None and end >= start
        segments.append(TranscriptSegment(
            text=text.strip(),
            start_time=format_offset(start) if with_timestamps and valid_times else None,
            end_time=format_offset(end) if with_timestamps and valid_times else None,
            language=language if isinstance(language, str) else None,
        ))
        logprob = _field(item, "avg_logprob")
        no_speech = _field(item, "no_speech_prob")
        if (isinstance(logprob, (float, int)) and logprob < -1.0) or (
            isinstance(no_speech, (float, int)) and no_speech > 0.6
        ):
            uncertainties.append(f"Check transcription segment {len(segments)} against the audio: Whisper reported low confidence or possible non-speech.")
    # Keep all spoken text in analysis if the provider's segment text is incomplete.
    if segments and " ".join(" ".join(s.text for s in segments).split()) != " ".join(raw.split()):
        segments = []
        uncertainties = []
        warnings.append("Segment text did not match the complete transcript; segment times were omitted to preserve the full text.")
    if not segments:
        segments = [TranscriptSegment(text=raw, language=language if isinstance(language, str) else None)]
    return TranscriptResult(
        raw_transcript=raw, segments=segments,
        language_notes=f"Whisper detected: {language}. Mixed-language passages still require review." if isinstance(language, str) and language else None,
        uncertainties=uncertainties, timestamp_source="asr_segment_offsets" if with_timestamps else "none",
        speakers_available=False, engine=ENGINE_GROQ, model=model, warnings=warnings,
    )


class GroqWhisperTranscriber(Transcriber):
    name = ENGINE_GROQ

    def __init__(self, client: groq.Groq | None = None, model: str = TRANSCRIPTION_MODEL) -> None:
        self._client = client
        self._model = model

    def transcribe(self, audio_path: Path, mime_type: str,
                   options: TranscriptionOptions | None = None) -> TranscriptResult:
        options = options or TranscriptionOptions()
        client = self._client
        try:
            client = client or create_client()
            kwargs: dict[str, Any] = {
                "model": self._model, "response_format": "verbose_json",
                "temperature": 0.0, "prompt": WHISPER_CONTEXT_PROMPT,
            }
            if options.with_timestamps:
                kwargs["timestamp_granularities"] = ["segment"]
            # Use transcription, never the English-only translations endpoint.
            # A generic filename keeps the original recording filename off the request.
            with audio_path.open("rb") as audio:
                response = client.audio.transcriptions.create(
                    file=(f"recording{audio_path.suffix}", audio, mime_type), **kwargs,
                )
            return parse_whisper_response(response, self._model, options.with_timestamps)
        except (NoSpeechError, TranscriptionError):
            raise
        except Exception as exc:
            raise translate_error(exc, TranscriptionError, "Groq transcription") from exc
        finally:
            if self._client is None and client is not None:
                close_client(client)
