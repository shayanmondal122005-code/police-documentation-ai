import json

import pytest
from pydantic import ValidationError

from config import AI_DRAFT_WARNING, REPORT_TITLE
from documentation.schemas import (
    UNKNOWN_PERSON,
    Contradiction,
    ModelReport,
    Person,
    PoliceReport,
    SourceRef,
    Statement,
)
from utils.groq import strict_schema


def test_mock_model_report_validates(mock_analysis_json):
    report = ModelReport.model_validate_json(mock_analysis_json)
    assert report.purpose.stated_purpose is None
    assert len(report.timeline) == 7


def test_minimal_report_needs_only_purpose_and_summary():
    report = ModelReport.model_validate({"purpose": {}, "executive_summary": "Summary."})
    assert report.persons == [] and report.contradictions == []


def test_missing_required_field_is_rejected(mock_analysis_dict):
    del mock_analysis_dict["executive_summary"]
    with pytest.raises(ValidationError):
        ModelReport.model_validate(mock_analysis_dict)


def test_invalid_classification_is_rejected():
    with pytest.raises(ValidationError):
        Statement(speaker="A", statement="x", classification="certainly true")


def test_person_without_name_becomes_unknown_person():
    assert Person(name="  ").name == UNKNOWN_PERSON


def test_source_ref_times_default_to_none_never_invented():
    ref = SourceRef(quote="x")
    assert ref.start_time is None and ref.end_time is None and ref.quote_verified is None


def test_police_report_carries_title_and_draft_warning(mock_analysis, integrity):
    from documentation.report_generator import build_admin_info
    from documentation.schemas import TranscriptMeta

    report = PoliceReport(
        admin=build_admin_info(mock_analysis, integrity, "Unavailable"),
        analysis=mock_analysis,
        transcript_meta=TranscriptMeta(engine="mock"),
    )
    assert report.title == REPORT_TITLE == "POLICE FIELD INTERACTION REPORT"
    assert report.ai_draft_warning == AI_DRAFT_WARNING


def test_json_schema_for_groq_is_serialisable_and_stripped_of_titles():
    schema = strict_schema(ModelReport.model_json_schema())
    assert '"title"' not in json.dumps(schema)
    assert "executive_summary" in schema["properties"]
    assert "executive_summary" in schema["required"]


def test_contradiction_requires_distinct_statements():
    with pytest.raises(ValidationError):
        Contradiction(statement_a="Same", statement_b="same", why_may_conflict="x")
