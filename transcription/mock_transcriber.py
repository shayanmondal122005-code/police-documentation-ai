"""Mock transcriber: returns a fixed local transcript so the pipeline runs without an API key.

No audio is read or sent anywhere. The transcript is the fixture in
`tests/fixtures/mock_transcript.json`, which contains no real person's data.
"""

from __future__ import annotations

import json
from pathlib import Path

from config import ENGINE_MOCK
from transcription.base import Transcriber, TranscriptionOptions, TranscriptResult

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "mock_transcript.json"


def load_mock_transcript(path: Path = FIXTURE_PATH) -> TranscriptResult:
    """Load the fixture transcript."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return TranscriptResult.model_validate(data)


class MockTranscriber(Transcriber):
    """Returns the fixture transcript regardless of the audio supplied."""

    name = ENGINE_MOCK

    def transcribe(
        self, audio_path: Path, mime_type: str, options: TranscriptionOptions | None = None
    ) -> TranscriptResult:
        result = load_mock_transcript()
        result.warnings = [*result.warnings, "MOCK transcript: not derived from the uploaded recording."]
        return result
