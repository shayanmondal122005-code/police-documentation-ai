"""Shared fixtures. No test here calls the real Gemini API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from documentation.schemas import ModelReport
from integrity.hashing import RecordingIntegrity
from transcription.base import TranscriptResult

FIXTURES = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture
def mock_transcript() -> TranscriptResult:
    return TranscriptResult.model_validate_json((FIXTURES / "mock_transcript.json").read_text(encoding="utf-8"))


@pytest.fixture
def mock_analysis_json() -> str:
    return (FIXTURES / "mock_model_report.json").read_text(encoding="utf-8")


@pytest.fixture
def mock_analysis(mock_analysis_json: str) -> ModelReport:
    return ModelReport.model_validate_json(mock_analysis_json)


@pytest.fixture
def mock_analysis_dict(mock_analysis_json: str) -> dict:
    return json.loads(mock_analysis_json)


@pytest.fixture
def integrity() -> RecordingIntegrity:
    return RecordingIntegrity(
        recording_id="REC-TEST00000001",
        filename="test.wav",
        size_bytes=10,
        sha256="a" * 64,
        processed_at="2026-01-01 00:00:00 UTC",
    )


class SequenceClient:
    """Report client that returns queued responses and records how often it was called."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []

    def generate_json(self, system_instruction: str, prompt: str, schema: dict) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
