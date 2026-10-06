"""Engine-independent transcription interface and result model.

Any speech-to-text engine (Gemini, Whisper, faster-whisper, ...) can be plugged in
by subclassing `Transcriber`. The report-generation layer only sees `TranscriptResult`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

TimestampSource = Literal["none", "asr_word_offsets", "model_reported"]


class TranscriptSegment(BaseModel):
    """One contiguous utterance. Speaker and times are None when not provided by the engine."""

    speaker: str | None = None
    text: str
    start_time: str | None = None
    end_time: str | None = None
    language: str | None = None


class TranscriptResult(BaseModel):
    """Structured transcript. `raw_transcript` is always the unmodified spoken text."""

    raw_transcript: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    language_notes: str | None = None
    uncertainties: list[str] = Field(default_factory=list)
    timestamp_source: TimestampSource = "none"
    speakers_available: bool = False
    engine: str = "unknown"
    model: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_availability_flags(self) -> "TranscriptResult":
        """Never claim timestamps/speakers that the segments do not actually contain."""
        has_times = any(s.start_time or s.end_time for s in self.segments)
        has_speakers = any(s.speaker for s in self.segments)
        if not has_times:
            self.timestamp_source = "none"
        if not has_speakers:
            self.speakers_available = False
        return self

    @property
    def timestamps_available(self) -> bool:
        return self.timestamp_source != "none"

    def to_analysis_text(self) -> str:
        """Render the transcript for the report model, including only real metadata."""
        if not self.segments:
            return self.raw_transcript
        lines: list[str] = []
        for index, seg in enumerate(self.segments, start=1):
            parts = [f"[{index}]"]
            if seg.start_time or seg.end_time:
                parts.append(f"[{seg.start_time or '?'}–{seg.end_time or '?'}]")
            if seg.speaker:
                parts.append(f"{seg.speaker}:")
            parts.append(seg.text)
            lines.append(" ".join(parts))
        return "\n".join(lines)


class TranscriptionOptions(BaseModel):
    """Per-request options. Engines ignore options they do not support."""

    with_timestamps: bool = True
    with_speakers: bool = True


class Transcriber(ABC):
    """Interface every transcription engine implements."""

    name: str = "transcriber"

    @abstractmethod
    def transcribe(
        self, audio_path: Path, mime_type: str, options: TranscriptionOptions | None = None
    ) -> TranscriptResult:
        """Transcribe the audio file at `audio_path`.

        Raises:
            NoSpeechError: no intelligible speech was found.
            TranscriptionError: the engine failed.
        """
