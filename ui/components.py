"""Reusable Streamlit rendering helpers. Free text from the model is always HTML-escaped."""

from __future__ import annotations

from html import escape

import streamlit as st

from config import AI_DRAFT_WARNING, APP_NAME, HASH_DISCLAIMER, PRIVACY_NOTICE
from documentation.render import TIME_UNAVAILABLE, time_label
from documentation.schemas import PoliceReport, SourceRef
from integrity.hashing import RecordingIntegrity
from utils.audio import format_size


def inject_css(css: str) -> None:
    st.markdown(css, unsafe_allow_html=True)


def render_header() -> None:
    st.markdown(
        f'<div class="pd-header"><h1>{escape(APP_NAME.upper())}</h1>'
        "<p>Draft documentation of field interactions from audio recordings — for officer review.</p></div>",
        unsafe_allow_html=True,
    )
    draft_banner()
    st.markdown(f'<div class="pd-notice">{escape(PRIVACY_NOTICE)}</div>', unsafe_allow_html=True)


def draft_banner() -> None:
    st.markdown(f'<div class="pd-draft-banner">{escape(AI_DRAFT_WARNING)}</div>', unsafe_allow_html=True)


def card(label: str, value: str, mono: bool = False) -> str:
    """HTML for one metadata card."""
    css = "value mono" if mono else "value"
    return f'<div class="pd-card"><div class="label">{escape(label)}</div><div class="{css}">{escape(value)}</div></div>'


def render_cards(items: list[tuple[str, str, bool]]) -> None:
    columns = st.columns(len(items))
    for column, (label, value, mono) in zip(columns, items):
        column.markdown(card(label, value, mono), unsafe_allow_html=True)


def render_integrity(integrity: RecordingIntegrity, duration: str) -> None:
    render_cards(
        [
            ("Recording ID", integrity.recording_id, False),
            ("Filename", integrity.filename, False),
            ("File size", format_size(integrity.size_bytes), False),
            ("Duration", duration, False),
        ]
    )
    st.markdown("")
    render_cards(
        [
            ("SHA-256", integrity.sha256, True),
            ("Processing timestamp", integrity.processed_at, False),
        ]
    )
    st.caption(HASH_DISCLAIMER)


def badge(classification: str) -> str:
    return f'<span class="pd-badge {escape(classification)}">{escape(classification.upper())}</span>'


def source_html(source: SourceRef | None) -> str:
    """Evidence-link line: time label, quote, and verification state."""
    label = time_label(source) if source else TIME_UNAVAILABLE
    parts = [f"Source: {escape(label)}"]
    if source and source.quote:
        parts.append(f"“{escape(source.quote)}”")
        if source.quote_verified is False:
            parts.append('<span class="pd-unverified">UNVERIFIED — quote not found in transcript</span>')
    return f'<div class="pd-source">{" — ".join(parts)}</div>'


def item(html_body: str, source: SourceRef | None = None) -> None:
    extra = source_html(source) if source is not None else ""
    st.markdown(f'<div class="pd-item">{html_body}{extra}</div>', unsafe_allow_html=True)


def render_review_flags(report: PoliceReport) -> None:
    for flag in report.review_flags:
        st.warning(flag)


def render_timeline(report: PoliceReport) -> None:
    events = sorted(report.analysis.timeline, key=lambda e: e.order)
    if not events:
        st.info("No events identified.")
    for event in events:
        item(f"<b>{escape(time_label(event.source))}</b> — {escape(event.description)}", event.source)


def render_statements(report: PoliceReport) -> None:
    a = report.analysis
    st.subheader("Important statements")
    for s in a.statements:
        item(f"<b>{escape(s.speaker)}</b> {badge(s.classification.value)}<br>{escape(s.statement)}", s.source)
    if not a.statements:
        st.info("None identified.")
    st.subheader("Allegations / claims")
    for al in a.allegations:
        item(f"{badge('allegation')} {escape(al.attributed_text())}", al.source)
    if not a.allegations:
        st.info("None identified.")
    st.subheader("Explicitly stated facts")
    for f in a.explicit_facts:
        item(f"{escape(f.text)} <i>(stated by {escape(f.stated_by)})</i>", f.source)
    if not a.explicit_facts:
        st.info("None identified.")
    st.subheader("Potential inconsistencies")
    for c in a.contradictions:
        body = (
            f"<b>Potential inconsistency</b> (confidence: {escape(c.confidence.value)})<br>"
            f"A: {escape(c.statement_a)}<br>B: {escape(c.statement_b)}<br>"
            f"<i>{escape(c.why_may_conflict)}</i><br>Speaker(s): {escape(', '.join(c.speakers) or 'unclear')}"
        )
        if c.qualification:
            body += f"<br>Qualification: {escape(c.qualification)}"
        item(body, c.source_a)
    if not a.contradictions:
        st.info("No potential inconsistencies identified.")


def render_evidence(report: PoliceReport) -> None:
    if not report.analysis.evidence:
        st.info("No evidence or material mentioned.")
    for e in report.analysis.evidence:
        by = f" <i>(mentioned by {escape(e.mentioned_by)})</i>" if e.mentioned_by else ""
        item(f"<b>{escape(e.category.value)}</b>: {escape(e.description)}{by}", e.source)
