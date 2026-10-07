"""Render a PoliceReport as Markdown.

Rendering is deterministic and enforces attribution: allegations are always printed as
"<speaker> alleged that ...", never as bare assertions.
"""

from __future__ import annotations

from collections.abc import Callable

from config import NOT_OFFICIAL_NOTICE
from documentation.schemas import NOT_PROVIDED, Contradiction, PoliceReport, SourceRef

TIME_UNAVAILABLE = "Timestamp unavailable"
Reference = Callable[[SourceRef | None], str]

_TIME_SOURCE_NOTES = {
    "none": "The transcript has no timestamps. No times are shown and none have been inferred.",
    "model_reported": "Times were reported by a general-purpose model and are unverified; check them against the recording.",
    "asr_word_offsets": "Times come from speech-recognition word offsets.",
    "asr_segment_offsets": "Times come from speech-recognition segment offsets; verify against the recording.",
}


def time_label(source: SourceRef | None) -> str:
    """'00:06–00:19', '00:06', or 'Timestamp unavailable'."""
    if source is None or not (source.start_time or source.end_time):
        return TIME_UNAVAILABLE
    if source.start_time and source.end_time and source.start_time != source.end_time:
        return f"{source.start_time}–{source.end_time}"
    return source.start_time or source.end_time or TIME_UNAVAILABLE


def source_note(source: SourceRef | None) -> str:
    """Short evidence link: time plus the quoted transcript excerpt and its verification state."""
    if source is None:
        return f"_Source: {TIME_UNAVAILABLE}_"
    note = f"Source: {time_label(source)}"
    if source.quote:
        status = {True: "", False: " — UNVERIFIED: quote not found in transcript", None: ""}[source.quote_verified]
        note += f' — "{source.quote}"{status}'
    return f"_{note}_"


class SourceIndex:
    """Stable references keep verbatim excerpts out of the narrative body."""

    def __init__(self) -> None:
        self.sources: list[SourceRef] = []
        self._labels: dict[tuple, str] = {}

    def reference(self, source: SourceRef | None) -> str:
        if source is None:
            return "[Source unavailable]"
        key = (source.source_type, source.start_time, source.end_time, source.quote, source.quote_verified)
        if key not in self._labels:
            self.sources.append(source)
            self._labels[key] = f"R{len(self.sources):02d}"
        status = "; UNVERIFIED" if source.quote_verified is False else ""
        return f"[{self._labels[key]}{status}]"

    def annexure(self) -> str:
        if not self.sources:
            return "_No source excerpts available._"
        return "\n\n".join(
            f"**R{index:02d}** — {source_note(source)}"
            for index, source in enumerate(self.sources, start=1)
        )


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "_None identified in the recording._"


def _admin_block(report: PoliceReport) -> str:
    a = report.admin
    recorded = set(a.fields_from_recording)

    def field(label: str, key: str, value: str | None) -> str:
        shown = value or NOT_PROVIDED
        suffix = " _(stated in recording)_" if key in recorded else ""
        return f"- **{label}:** {shown}{suffix}"

    rows = [
        field("Police station", "police_station", a.police_station),
        field("District", "district", a.district),
        field("Case / reference number", "case", a.case_reference),
        field("Officer", "officer", a.officer),
        field("Rank / designation", "officer_rank", a.officer_rank),
        field("Date", "date", a.date),
        field("Time", "time", a.time),
        field("Location", "location", a.location),
    ]
    return "\n".join(rows)


def _recording_block(report: PoliceReport) -> str:
    a = report.admin
    return "\n".join([
        f"- **Recording filename:** {a.recording_filename}",
        f"- **Recording duration:** {a.recording_duration}",
        f"- **Recording ID:** {a.recording_id}",
        f"- **SHA-256:** `{a.sha256}`",
        f"- **Processing timestamp:** {a.processing_timestamp}",
    ])


def _purpose(report: PoliceReport) -> str:
    p = report.analysis.purpose
    return "\n".join(
        [
            f"- **Directly stated purpose:** {p.stated_purpose or 'Not directly stated in the recording.'}",
            f"- **Inferred purpose (not stated):** {p.inferred_purpose or 'None inferred.'}",
            f"- **Basis:** {p.basis.value}",
        ]
    )


def _persons(report: PoliceReport, reference: Reference) -> str:
    rows = []
    for person in report.analysis.persons:
        role = person.role or "Role not stated"
        info = f" — {person.relevant_info}" if person.relevant_info else ""
        rows.append(f"**{person.name}** ({role}){info.rstrip('.')}. {reference(person.source)}")
    return _bullets(rows)


def _timeline(report: PoliceReport, reference: Reference) -> str:
    events = sorted(report.analysis.timeline, key=lambda e: e.order)
    rows = [f"{index}. **{time_label(e.source)}** — {e.description} {reference(e.source)}"
            for index, e in enumerate(events, start=1)]
    return "\n\n".join(rows) if rows else "_No material events identified in the recording._"


def _statements(report: PoliceReport, reference: Reference) -> str:
    rows = [
        f"{index}. **{s.speaker}** ({s.classification.value}): {s.statement} {reference(s.source)}"
        for index, s in enumerate(report.analysis.statements, start=1)
    ]
    return "\n\n".join(rows) if rows else "_No material statements identified in the recording._"


def _facts(report: PoliceReport, reference: Reference) -> str:
    rows = [
        f"- {f.text} _(stated by {f.stated_by})_ {reference(f.source)}" for f in report.analysis.explicit_facts
    ]
    return "\n".join(rows) if rows else "_None identified in the recording._"


def _allegations(report: PoliceReport, reference: Reference) -> str:
    rows = [f"- {a.attributed_text()} {reference(a.source)}" for a in report.analysis.allegations]
    return "\n".join(rows) if rows else "_None identified in the recording._"


def format_contradiction(index: int, c: Contradiction, reference: Reference = source_note) -> str:
    """Markdown block for one potential inconsistency."""
    speakers = ", ".join(c.speakers) if c.speakers else "Speaker(s) unclear"
    lines = [
        f"{index}. **Potential inconsistency** (confidence: {c.confidence.value})",
        f"   - Statement A: {c.statement_a} {reference(c.source_a)}",
        f"   - Statement B: {c.statement_b} {reference(c.source_b)}",
        f"   - Why they may conflict: {c.why_may_conflict}",
        f"   - Speaker(s): {speakers}",
    ]
    if c.qualification:
        lines.append(f"   - Qualification: {c.qualification}")
    return "\n".join(lines)


def _contradictions(report: PoliceReport, reference: Reference) -> str:
    rows = [format_contradiction(i, c, reference) for i, c in enumerate(report.analysis.contradictions, start=1)]
    return "\n".join(rows) if rows else "_No potential inconsistencies identified._"


def _evidence(report: PoliceReport, reference: Reference) -> str:
    rows = []
    for e in report.analysis.evidence:
        by = f" _(mentioned by {e.mentioned_by})_" if e.mentioned_by else ""
        rows.append(f"- **{e.category.value}:** {e.description}{by} {reference(e.source)}")
    return "\n".join(rows) if rows else "_No evidence or material mentioned._"


def _follow_ups(report: PoliceReport) -> str:
    return _bullets([f"{f.action} _(basis: {f.basis})_" for f in report.analysis.follow_up_actions])


def _uncertainties(report: PoliceReport, reference: Reference) -> str:
    meta = report.transcript_meta
    rows = [
        f"- **{u.kind.value.capitalize()}:** {u.description} {reference(u.source)}"
        for u in report.analysis.uncertainties
    ]
    rows.append(f"- **Timestamps:** {_TIME_SOURCE_NOTES.get(meta.timestamp_source, '')}")
    if meta.language_notes:
        rows.append(f"- **Language notes:** {meta.language_notes}")
    rows += [f"- **Transcription note:** {w}" for w in meta.warnings]
    return "\n".join(rows)


def _review_flags(report: PoliceReport) -> str:
    if not report.review_flags:
        return ""
    return "**Automated review flags**\n\n" + _bullets(report.review_flags) + "\n\n"


def report_to_markdown(report: PoliceReport) -> str:
    """Full report body (no officer-review section; that is added at export time)."""
    a = report.analysis
    sources = SourceIndex()
    body = (
        f"# {report.title}\n\n"
        f"> **{report.ai_draft_warning}**\n>\n> {NOT_OFFICIAL_NOTICE}\n\n"
        f"## Administrative Information\n\n{_admin_block(report)}\n\n"
        f"## 1. Purpose of Interaction\n\n{_purpose(report)}\n\n"
        f"## 2. Incident Narrative\n\n{a.executive_summary}\n\n"
        f"## 3. Persons Present or Referred To\n\n{_persons(report, sources.reference)}\n\n"
        f"## 4. Chronological Account\n\n{_timeline(report, sources.reference)}\n\n"
        f"## 5. Material Statements\n\n{_statements(report, sources.reference)}\n\n"
        f"## 6. Information Reported\n\n"
        "The following records what was stated; independent verification is required.\n\n"
        f"{_facts(report, sources.reference)}\n\n"
        f"## 7. Allegations and Claims\n\n{_allegations(report, sources.reference)}\n\n"
        f"## 8. Potential Inconsistencies\n\n{_contradictions(report, sources.reference)}\n\n"
        f"## 9. Matters Requiring Verification\n\n{_bullets(a.unresolved_questions)}\n\n"
        f"## 10. Proposed Follow-up Actions\n\n"
        "Suggested verification steps for officer consideration; completion is not established by this report.\n\n"
        f"{_follow_ups(report)}\n\n"
        f"## 11. Evidence and Material Mentioned\n\n"
        "Items mentioned in the recording; possession, collection or seizure is not established here.\n\n"
        f"{_evidence(report, sources.reference)}\n\n"
        f"## 12. Reliability and Review Notes\n\n{_uncertainties(report, sources.reference)}\n\n"
        f"{_review_flags(report)}"
    )
    return (
        body
        + "## Annexure A — Source References\n\n"
        + "References link the report to verbatim transcript excerpts. Recording offsets are not incident clock times.\n\n"
        + sources.annexure()
        + f"\n\n## Annexure B — Recording Details\n\n{_recording_block(report)}\n"
    )
