import copy
import json

import pytest

from documentation.clients import MockReportClient
from documentation.render import report_to_markdown
from documentation.report_generator import build_admin_info, generate_report
from documentation.schemas import NOT_PROVIDED, ModelReport
from errors import NoSpeechError, ReportValidationError
from tests.conftest import SequenceClient
from transcription.base import TranscriptResult, TranscriptSegment


def test_mock_pipeline_generates_complete_report(mock_transcript, integrity):
    report = generate_report(mock_transcript, integrity, MockReportClient(), duration="1:15")
    assert report.title == "POLICE FIELD INTERACTION REPORT"
    assert report.admin.recording_id == integrity.recording_id
    assert report.admin.sha256 == integrity.sha256
    assert report.review_flags == []  # mock quotes are all verbatim
    assert len(report.analysis.timeline) == 7
    markdown = report_to_markdown(report)
    for heading in ("Purpose of Interaction", "Incident Narrative", "Persons Present or Referred To", "Chronological Account",
                    "Material Statements", "Information Reported", "Allegations and Claims",
                    "Potential Inconsistencies", "Matters Requiring Verification", "Proposed Follow-up Actions",
                    "Evidence and Material Mentioned", "Reliability and Review Notes", "Annexure A", "Annexure B"):
        assert heading in markdown
    assert "AI-GENERATED DRAFT — REQUIRES OFFICER REVIEW" in markdown
    assert integrity.sha256 in markdown


def test_empty_transcript_is_rejected(integrity):
    empty = TranscriptResult(raw_transcript="   ")
    with pytest.raises(NoSpeechError):
        generate_report(empty, integrity, MockReportClient())


def test_missing_metadata_is_never_guessed(mock_analysis, integrity):
    admin = build_admin_info(mock_analysis, integrity, "Unavailable")
    assert admin.case_reference is None and admin.officer is None
    assert admin.date is None and admin.time is None and admin.location is None
    assert admin.fields_from_recording == []


def test_missing_metadata_renders_as_not_provided(mock_transcript, integrity):
    report = generate_report(mock_transcript, integrity, MockReportClient())
    markdown = report_to_markdown(report)
    assert f"**Officer:** {NOT_PROVIDED}" in markdown
    assert f"**Location:** {NOT_PROVIDED}" in markdown


def test_user_metadata_overrides_model_guesses(mock_analysis_dict, mock_transcript, integrity):
    mock_analysis_dict["detected_metadata"] = {"date": "1999-01-01", "time": "03:00", "location": "Model Town"}
    client = SequenceClient(json.dumps(mock_analysis_dict))
    report = generate_report(
        mock_transcript, integrity, client, date="2026-10-06", location="Station Road", officer=" SI Verma "
    )
    assert report.admin.date == "2026-10-06"
    assert report.admin.location == "Station Road"
    assert report.admin.officer == "SI Verma"
    # only the field the officer left blank came from the recording, and it is labelled as such
    assert report.admin.time == "03:00"
    assert report.admin.fields_from_recording == ["time"]
    assert "(stated in recording)" in report_to_markdown(report)


def test_malformed_json_is_retried_then_succeeds(mock_transcript, integrity, mock_analysis_json):
    client = SequenceClient("this is not json", mock_analysis_json)
    report = generate_report(mock_transcript, integrity, client)
    assert client.calls == 2
    assert "failed schema validation" in client.prompts[1]
    assert report.analysis.executive_summary


def test_persistently_malformed_output_raises_controlled_error(mock_transcript, integrity):
    client = SequenceClient("{not valid")
    with pytest.raises(ReportValidationError) as info:
        generate_report(mock_transcript, integrity, client)
    assert client.calls == 2
    assert "did not match the required structure" in info.value.user_message


def test_schema_violation_is_not_silently_accepted(mock_transcript, integrity, mock_analysis_dict):
    mock_analysis_dict["statements"][0]["classification"] = "definitely true"
    client = SequenceClient(json.dumps(mock_analysis_dict))
    with pytest.raises(ReportValidationError):
        generate_report(mock_transcript, integrity, client)


def test_validation_feedback_does_not_echo_transcript_text(mock_transcript, integrity, mock_analysis_dict):
    mock_analysis_dict["statements"][0]["classification"] = "सुनील यादव secret"
    client = SequenceClient(json.dumps(mock_analysis_dict), json.dumps(mock_analysis_dict))
    with pytest.raises(ReportValidationError):
        generate_report(mock_transcript, integrity, client)
    assert "secret" not in client.prompts[1].split("failed schema validation")[1]


def test_timestamps_are_stripped_when_transcript_has_none(integrity, mock_analysis_json):
    transcript = TranscriptResult(
        raw_transcript="\n".join(
            s["text"] for s in json.loads(open("sample_data/mock_transcript.json", encoding="utf-8").read())["segments"]
        ),
        segments=[TranscriptSegment(text="x")],
    )
    assert not transcript.timestamps_available
    report = generate_report(transcript, integrity, SequenceClient(mock_analysis_json))
    assert all(
        s.source is None or (s.source.start_time is None and s.source.end_time is None)
        for s in report.analysis.statements
    )
    assert any("timestamps although the transcript has none" in f for f in report.review_flags)
    assert "Timestamp unavailable" in report_to_markdown(report)


def test_unverifiable_quote_is_flagged_not_trusted(mock_transcript, integrity, mock_analysis_dict):
    data = copy.deepcopy(mock_analysis_dict)
    data["statements"][0]["source"]["quote"] = "यह वाक्य रिकॉर्डिंग में नहीं है"
    report = generate_report(mock_transcript, integrity, SequenceClient(json.dumps(data)))
    assert report.analysis.statements[0].source.quote_verified is False
    assert any("could not be found in the transcript" in f for f in report.review_flags)
    assert "UNVERIFIED" in report_to_markdown(report)


def test_report_generation_does_not_modify_raw_transcript(mock_transcript, integrity):
    before = mock_transcript.raw_transcript
    generate_report(mock_transcript, integrity, MockReportClient())
    assert mock_transcript.raw_transcript == before


def test_model_report_roundtrip(mock_analysis):
    assert ModelReport.model_validate_json(mock_analysis.model_dump_json()) == mock_analysis
