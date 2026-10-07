"""End-to-end processing: upload -> integrity -> transcription -> report.

The UI calls `run_pipeline`; nothing here imports Streamlit, so it is fully testable.
"""

from __future__ import annotations

import io
import wave
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from config import ASR_TIMESTAMP_DIARIZATION_MAX_MINUTES, ENGINE_ASR, ENGINE_MOCK, ENGINE_PROMPTED, GeminiModels, get_api_key
from documentation.clients import GeminiReportClient, MockReportClient, ReportModelClient
from documentation.render import report_to_markdown
from documentation.report_generator import generate_report
from documentation.schemas import PoliceReport
from errors import ConfigurationError, NoSpeechError
from integrity.hashing import RecordingIntegrity, build_integrity
from transcription.base import Transcriber, TranscriptionOptions, TranscriptResult
from transcription.gemini_transcriber import GeminiASRTranscriber, GeminiPromptedTranscriber
from transcription.mock_transcriber import MockTranscriber
from utils.audio import detect_duration_seconds, format_duration, get_extension, temporary_audio_file, validate_upload
from utils.gemini import create_client

ProgressCallback = Callable[[str], None]
logger = logging.getLogger(__name__)

STEP_UPLOADED = "Recording uploaded"
STEP_PROCESSED = "Audio processed"
STEP_TRANSCRIBED = "Speech transcribed"
STEP_ANALYSED = "Structured analysis generated"
STEP_TIMELINE = "Timeline generated"
STEP_DOCUMENTED = "Documentation generated"
PIPELINE_STEPS = (STEP_UPLOADED, STEP_PROCESSED, STEP_TRANSCRIBED, STEP_ANALYSED, STEP_TIMELINE, STEP_DOCUMENTED)


@dataclass
class ReportMetadata:
    """Officer-entered details; these always override anything found in the recording."""

    case_reference: str = ""
    officer: str = ""
    date: str = ""
    time: str = ""
    location: str = ""


@dataclass
class PipelineResult:
    integrity: RecordingIntegrity
    duration: str
    transcript: TranscriptResult
    report: PoliceReport
    markdown: str
    report_model: str | None = None


def build_engines(engine: str, api_key: str | None = None,
                  models: GeminiModels | None = None) -> tuple[Transcriber, ReportModelClient]:
    """Return the (transcriber, report client) pair for an engine key."""
    if engine == ENGINE_MOCK:
        return MockTranscriber(), MockReportClient()
    if engine not in (ENGINE_ASR, ENGINE_PROMPTED):
        raise ConfigurationError(f"Unknown transcription engine: {engine}")
    api_key = api_key or get_api_key()
    if not api_key:
        raise ConfigurationError(
            "No Gemini API key found. Add GEMINI_API_KEY to your .env file (see .env.example), "
            "or choose the Mock engine to try the app without an API key."
        )
    client = create_client(api_key)
    models = models or GeminiModels()
    report_client = GeminiReportClient(client=client, model=models.report, fallback_model=models.fallback)
    if engine == ENGINE_ASR:
        return GeminiASRTranscriber(client=client, model=models.asr), report_client
    return GeminiPromptedTranscriber(client=client, model=models.prompted, fallback_model=models.fallback), report_client


def demo_recording() -> tuple[str, bytes]:
    """A silent placeholder for the explicitly fictional, offline demo."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 8000)
    return "fictional_demo.wav", buffer.getvalue()


def prepare_recording(filename: str, data: bytes) -> tuple[str, RecordingIntegrity, str]:
    """Validate an upload, hash it, and report its duration. Returns (mime, integrity, duration)."""
    mime_type = validate_upload(filename, len(data))
    integrity = build_integrity(io.BytesIO(data), filename)
    duration = format_duration(detect_duration_seconds(data, filename))
    return mime_type, integrity, duration


def run_pipeline(
    filename: str,
    data: bytes,
    engine: str,
    options: TranscriptionOptions,
    metadata: ReportMetadata,
    progress: ProgressCallback | None = None,
    api_key: str | None = None,
    models: GeminiModels | None = None,
) -> PipelineResult:
    """Run the full pipeline. `progress` is called with a step name as each step completes."""
    notify = progress or (lambda _step: None)

    mime_type, integrity, duration = prepare_recording(filename, data)
    if engine == ENGINE_ASR and (options.with_timestamps or options.with_speakers):
        seconds = detect_duration_seconds(data, filename)
        if seconds is not None and seconds > ASR_TIMESTAMP_DIARIZATION_MAX_MINUTES * 60:
            raise ConfigurationError("This recording exceeds the 30-minute ASR limit. Turn off timestamps and speaker labels, or use the prompted engine.")
    transcriber, report_client = build_engines(engine, api_key, models)
    notify(STEP_UPLOADED)

    try:
        with temporary_audio_file(data, get_extension(filename)) as audio_path:
            notify(STEP_PROCESSED)
            transcript = _transcribe(transcriber, audio_path, mime_type, options)
        notify(STEP_TRANSCRIBED)

        report = generate_report(
            transcript,
            integrity,
            report_client,
            duration=duration,
            case_reference=metadata.case_reference,
            officer=metadata.officer,
            date=metadata.date,
            time=metadata.time,
            location=metadata.location,
        )
    finally:
        # Both engines share one request-scoped client; never keep connections alive across reports.
        client = getattr(report_client, "_client", None)
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                logger.warning("Could not close Gemini client: %s", type(exc).__name__)
    notify(STEP_ANALYSED)
    notify(STEP_TIMELINE)
    markdown = report_to_markdown(report)
    notify(STEP_DOCUMENTED)
    return PipelineResult(integrity, duration, transcript, report, markdown,
                          report_model=getattr(report_client, "actual_model", None))


def _transcribe(
    transcriber: Transcriber, audio_path: Path, mime_type: str, options: TranscriptionOptions
) -> TranscriptResult:
    transcript = transcriber.transcribe(audio_path, mime_type, options)
    if not transcript.raw_transcript.strip():
        raise NoSpeechError("No intelligible speech was detected in this recording.")
    return transcript
