"""Check that formal presentation preserves attribution and the audit trail."""

import io
import re

from docx import Document
from docx.oxml.ns import qn

from documentation.clients import MockReportClient
from documentation.render import report_to_markdown
from documentation.report_generator import generate_report
from export.document_export import compose_document, export_docx, export_txt


def test_quotes_are_deduplicated_in_annexure_and_references_resolve(mock_transcript, integrity):
    report = generate_report(mock_transcript, integrity, MockReportClient())
    document = report_to_markdown(report)
    body, annexures = document.split("## Annexure A", 1)
    references = set(re.findall(r"\[(R\d+)(?:; UNVERIFIED)?\]", body))
    labels = re.findall(r"\*\*(R\d+)\*\*", annexures)
    assert references and references == set(labels)
    assert len(labels) == len(set(labels))
    assert "Source:" not in body
    quote = report.analysis.statements[0].source.quote
    assert quote in annexures
    assert annexures.count(f'"{quote}"') == 1
    assert report.admin.sha256 not in body
    assert report.admin.sha256 in annexures
    # Changing presentation does not change the recording or validated analysis.
    assert mock_transcript.raw_transcript
    assert report.analysis.allegations[0].attributed_text() in body


def test_unverified_sources_remain_visible_in_body_and_annexure(mock_transcript, integrity):
    report = generate_report(mock_transcript, integrity, MockReportClient())
    report.analysis.statements[0].source.quote_verified = False
    report.analysis.statements[0].source.quote = "असत्यापित उद्धरण"
    body, annexures = report_to_markdown(report).split("## Annexure A", 1)
    assert "; UNVERIFIED]" in body
    assert "UNVERIFIED: quote not found in transcript" in annexures
    assert "असत्यापित उद्धरण" in annexures


def test_station_fields_only_come_from_officer_entries(mock_transcript, integrity):
    report = generate_report(mock_transcript, integrity, MockReportClient(),
                             police_station=" Sample Station ", district=" Sample District ", officer_rank=" SI ")
    assert report.admin.police_station == "Sample Station"
    assert report.admin.district == "Sample District"
    assert report.admin.officer_rank == "SI"
    blank = generate_report(mock_transcript, integrity, MockReportClient())
    assert blank.admin.police_station is None and blank.admin.district is None and blank.admin.officer_rank is None
    assert "**Police station:** Not provided" in report_to_markdown(blank)


def test_exports_keep_formal_sections_corrections_and_signoff(mock_transcript, integrity):
    report = generate_report(mock_transcript, integrity, MockReportClient(), police_station="Sample Station")
    document = compose_document(report_to_markdown(report), "Reviewed against recording.")
    word = Document(io.BytesIO(export_docx(document)))
    word_text = "\n".join(p.text for p in word.paragraphs)
    plain_text = export_txt(document).decode()
    for text in (word_text, plain_text):
        assert "Incident Narrative" in text and "Source References" in text
        assert "Sample Station" in text and "Reviewed against recording." in text
        assert "Reviewing officer" in text and "Signature" in text
        assert report.analysis.statements[0].source.quote in text
    assert str(word.styles["Title"].font.color.rgb) == "000000"
    assert str(word.styles["Heading 1"].font.color.rgb) == "000000"
    assert word.styles["Title"].element.find(".//" + qn("w:pBdr")) is None
    assert word.sections[0].footer._element.find(".//" + qn("w:fldSimple")).get(qn("w:instr")) == "PAGE"
