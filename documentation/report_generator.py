"""Transcript -> validated, guard-railed PoliceReport."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from config import REPORT_MAX_ATTEMPTS
from documentation.clients import ReportModelClient
from documentation.guardrails import run_guardrails
from documentation.schemas import (
    AdministrativeInfo,
    ModelReport,
    PoliceReport,
    TranscriptMeta,
)
from errors import NoSpeechError, ReportValidationError
from integrity.hashing import RecordingIntegrity
from prompts.documentation_prompt import DOCUMENTATION_SYSTEM_INSTRUCTION, build_documentation_prompt
from transcription.base import TranscriptResult

logger = logging.getLogger(__name__)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def build_admin_info(
    analysis: ModelReport,
    integrity: RecordingIntegrity,
    duration: str,
    case_reference: str | None = None,
    officer: str | None = None,
    date: str | None = None,
    time: str | None = None,
    location: str | None = None,
) -> AdministrativeInfo:
    """Merge officer-entered metadata with details the recording explicitly states.

    Officer-entered values always win. A recording-derived value is used only when the
    officer left the field blank, and is recorded in `fields_from_recording`.
    """
    entered = {"date": _clean(date), "time": _clean(time), "location": _clean(location)}
    detected = analysis.detected_metadata
    from_recording = {
        "date": _clean(detected.date),
        "time": _clean(detected.time),
        "location": _clean(detected.location),
    }
    merged: dict[str, str | None] = {}
    used_recording: list[str] = []
    for key, entered_value in entered.items():
        if entered_value:
            merged[key] = entered_value
        elif from_recording[key]:
            merged[key] = from_recording[key]
            used_recording.append(key)
        else:
            merged[key] = None
    return AdministrativeInfo(
        case_reference=_clean(case_reference),
        officer=_clean(officer),
        recording_filename=integrity.filename,
        recording_duration=duration,
        recording_id=integrity.recording_id,
        sha256=integrity.sha256,
        processing_timestamp=integrity.processed_at,
        fields_from_recording=used_recording,
        **merged,
    )


def _validation_feedback(error: ValidationError) -> str:
    """Describe schema problems by location and type only (never echoing model/transcript text)."""
    problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in error.errors()[:10]]
    return "Your previous output failed schema validation: " + "; ".join(problems)


def request_analysis(transcript: TranscriptResult, client: ReportModelClient) -> ModelReport:
    """Ask the model for a ModelReport, validating and retrying on malformed output."""
    prompt = build_documentation_prompt(
        transcript.to_analysis_text(), transcript.language_notes, transcript.uncertainties
    )
    schema = ModelReport.model_json_schema()
    feedback = ""
    for attempt in range(1, REPORT_MAX_ATTEMPTS + 1):
        raw = client.generate_json(DOCUMENTATION_SYSTEM_INSTRUCTION, prompt + feedback, schema)
        try:
            return ModelReport.model_validate_json(raw)
        except ValidationError as exc:
            logger.warning("Report validation failed (attempt %d): %d error(s)", attempt, exc.error_count())
            feedback = "\n\n" + _validation_feedback(exc)
    raise ReportValidationError(
        "The AI returned a report that did not match the required structure, even after a retry. "
        "No report was produced. Please try again."
    )


def generate_report(
    transcript: TranscriptResult,
    integrity: RecordingIntegrity,
    client: ReportModelClient,
    duration: str = "Unavailable",
    case_reference: str | None = None,
    officer: str | None = None,
    date: str | None = None,
    time: str | None = None,
    location: str | None = None,
) -> PoliceReport:
    """Generate the full PoliceReport from a transcript."""
    if not transcript.raw_transcript.strip():
        raise NoSpeechError("The transcript is empty, so no report can be generated.")
    analysis = request_analysis(transcript, client)
    flags = run_guardrails(analysis, transcript)
    return PoliceReport(
        admin=build_admin_info(analysis, integrity, duration, case_reference, officer, date, time, location),
        analysis=analysis,
        transcript_meta=TranscriptMeta(
            engine=transcript.engine,
            model=transcript.model,
            timestamp_source=transcript.timestamp_source,
            speakers_available=transcript.speakers_available,
            language_notes=transcript.language_notes,
            warnings=transcript.warnings,
        ),
        review_flags=flags,
    )
