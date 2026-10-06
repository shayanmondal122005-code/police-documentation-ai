"""Allegations stay allegations; beliefs and hearsay never become facts."""

import json

from documentation.guardrails import downgrade_hedged_facts
from documentation.render import report_to_markdown
from documentation.report_generator import generate_report
from documentation.schemas import Allegation, ModelReport, SourceRef, StatedFact, Statement, StatementType
from tests.conftest import SequenceClient


def test_allegation_text_always_carries_attribution():
    allegation = Allegation(alleged_by="Speaker 2", claim="Rahul took the phone.")
    assert allegation.attributed_text() == "Speaker 2 alleged that Rahul took the phone."


def test_allegation_defaults_to_unknown_speaker_not_bare_assertion():
    assert Allegation(claim="Rahul took the phone").attributed_text() == "Unknown speaker alleged that Rahul took the phone."


def test_hindi_belief_marked_as_fact_is_reclassified_as_belief():
    analysis = ModelReport.model_validate(
        {
            "purpose": {},
            "executive_summary": "s",
            "statements": [
                {
                    "speaker": "Speaker 2",
                    "statement": "Rahul was there.",
                    "classification": "fact",
                    "source": {"quote": "मुझे लगता है कि राहुल वहाँ था।"},
                }
            ],
        }
    )
    flags = downgrade_hedged_facts(analysis)
    assert analysis.statements[0].classification is StatementType.BELIEF
    assert flags and "belief" in flags[0]


def test_bhojpuri_and_english_hedges_are_detected():
    for quote in ("हमरा बुझाता कि राहुल उहाँ रहल", "I think Rahul was there"):
        analysis = ModelReport(
            purpose={},
            executive_summary="s",
            statements=[Statement(speaker="A", statement="x", classification="fact", source=SourceRef(quote=quote))],
        )
        downgrade_hedged_facts(analysis)
        assert analysis.statements[0].classification is StatementType.BELIEF, quote


def test_hearsay_marked_as_fact_is_reclassified_as_hearsay():
    analysis = ModelReport(
        purpose={},
        executive_summary="s",
        statements=[
            Statement(speaker="A", statement="x", classification="fact", source=SourceRef(quote="मैंने सुना है कि राहुल का भाई वहीं था"))
        ],
    )
    downgrade_hedged_facts(analysis)
    assert analysis.statements[0].classification is StatementType.HEARSAY


def test_hedged_item_in_explicit_facts_is_moved_out_of_facts():
    analysis = ModelReport(
        purpose={},
        executive_summary="s",
        explicit_facts=[
            StatedFact(text="Rahul was present.", stated_by="Speaker 2", source=SourceRef(quote="मुझे लगता है कि राहुल वहाँ था।")),
            StatedFact(text="The speaker gave a name.", stated_by="Speaker 2", source=SourceRef(quote="मेरा नाम सुनील यादव है।")),
        ],
    )
    flags = downgrade_hedged_facts(analysis)
    assert [f.text for f in analysis.explicit_facts] == ["The speaker gave a name."]
    assert analysis.statements[0].classification is StatementType.BELIEF
    assert analysis.statements[0].statement == "Rahul was present."
    assert len(flags) == 1


def test_genuine_facts_are_left_alone():
    analysis = ModelReport(
        purpose={},
        executive_summary="s",
        statements=[Statement(speaker="A", statement="x", classification="fact", source=SourceRef(quote="मेरा नाम सुनील यादव है।"))],
    )
    assert downgrade_hedged_facts(analysis) == []
    assert analysis.statements[0].classification is StatementType.FACT


def test_end_to_end_allegation_and_belief_stay_separate_from_facts(mock_transcript, integrity, mock_analysis_json):
    report = generate_report(mock_transcript, integrity, SequenceClient(mock_analysis_json))
    markdown = report_to_markdown(report)
    allegations = markdown.split("## 7. Allegations / Claims")[1].split("## 8.")[0]
    facts = markdown.split("## 6. Explicitly Stated Facts")[1].split("## 7.")[0]
    assert "Speaker 2 alleged that Rahul took their phone." in allegations
    assert "Rahul took" not in facts
    assert "Rahul was there" not in markdown
    assert any(
        s.classification is StatementType.BELIEF and "belief" in s.statement for s in report.analysis.statements
    )


def test_end_to_end_model_mislabelling_belief_as_fact_is_corrected(mock_transcript, integrity, mock_analysis_dict):
    stmt = mock_analysis_dict["statements"][1]
    assert stmt["classification"] == "belief"
    stmt["classification"] = "fact"
    stmt["statement"] = "Rahul was there."
    report = generate_report(mock_transcript, integrity, SequenceClient(json.dumps(mock_analysis_dict)))
    assert report.analysis.statements[1].classification is StatementType.BELIEF
    assert any("re-classified from fact to belief" in f for f in report.review_flags)
