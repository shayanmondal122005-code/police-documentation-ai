"""Contradictions are formatted conservatively and never fabricated or accusatory."""

import json

import pytest
from pydantic import ValidationError

from documentation.guardrails import find_prohibited_language
from documentation.render import format_contradiction, report_to_markdown
from documentation.report_generator import generate_report
from documentation.schemas import Confidence, Contradiction, SourceRef
from tests.conftest import SequenceClient


def make(**overrides):
    base = dict(
        statement_a="I arrived at nine.",
        statement_b="I arrived at eight.",
        speakers=["Speaker 2"],
        why_may_conflict="The two statements appear inconsistent regarding the reported arrival time.",
        source_a=SourceRef(start_time="00:23", end_time="00:30", quote="नौ बजे"),
        source_b=SourceRef(quote="आठ बजे"),
    )
    base.update(overrides)
    return Contradiction(**base)


def test_formatting_contains_all_required_parts():
    text = format_contradiction(1, make(confidence=Confidence.MEDIUM, qualification="Both times are approximate."))
    assert "**Potential inconsistency** (confidence: medium)" in text
    assert "Statement A: I arrived at nine." in text
    assert "Statement B: I arrived at eight." in text
    assert "Why they may conflict:" in text
    assert "Speaker(s): Speaker 2" in text
    assert "Source: 00:23–00:30" in text
    assert "Source: Timestamp unavailable" in text  # B has no times: never invented
    assert "Qualification: Both times are approximate." in text


def test_formatting_without_speakers_is_explicit():
    assert "Speaker(s) unclear" in format_contradiction(1, make(speakers=[]))


def test_confidence_defaults_to_low():
    assert make().confidence is Confidence.LOW


@pytest.mark.parametrize(
    "overrides",
    [
        {"statement_a": ""},
        {"statement_b": "   "},
        {"why_may_conflict": ""},
        {"statement_b": "I ARRIVED AT NINE."},
    ],
)
def test_incomplete_or_identical_contradictions_are_rejected(overrides):
    with pytest.raises(ValidationError):
        make(**overrides)


def test_empty_contradiction_list_renders_no_fabricated_entries(mock_transcript, integrity, mock_analysis_dict):
    mock_analysis_dict["contradictions"] = []
    report = generate_report(mock_transcript, integrity, SequenceClient(json.dumps(mock_analysis_dict)))
    section = report_to_markdown(report).split("## 8.")[1].split("## 9.")[0]
    assert "No potential inconsistencies identified." in section
    assert "Statement A" not in section


@pytest.mark.parametrize("word", ["lied", "lying", "liar", "guilty", "confessed", "culprit"])
def test_accusatory_language_is_detected(word):
    assert find_prohibited_language(f"The witness {word} about the time.")


def test_neutral_language_is_not_flagged():
    assert find_prohibited_language("The two statements appear inconsistent regarding the reported time.") == []


def test_model_saying_witness_lied_is_flagged_for_review(mock_transcript, integrity, mock_analysis_dict):
    mock_analysis_dict["contradictions"][0]["why_may_conflict"] = "The witness lied about the time."
    report = generate_report(mock_transcript, integrity, SequenceClient(json.dumps(mock_analysis_dict)))
    assert any("lied" in flag for flag in report.review_flags)


def test_mock_report_uses_potential_inconsistency_wording(mock_transcript, integrity, mock_analysis_json):
    report = generate_report(mock_transcript, integrity, SequenceClient(mock_analysis_json))
    assert len(report.analysis.contradictions) == 1
    markdown = report_to_markdown(report)
    assert "Potential inconsistency" in markdown
    assert "appear inconsistent" in markdown
    assert "lied" not in markdown.lower()
