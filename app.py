"""Police Documentation AI - Streamlit entry point.

Run with:  streamlit run app.py
This file only wires the UI to `pipeline.run_pipeline`; all logic lives in the packages.
"""

from __future__ import annotations

import logging

import streamlit as st

from config import (
    APP_NAME,
    ENGINE_LABELS,
    ENGINE_MOCK,
    ENGINE_GROQ,
    SUPPORTED_EXTENSIONS,
)
from errors import ExportError, UserFacingError
from export.document_export import (
    compose_document,
    export_docx,
    export_filename,
    export_markdown,
    export_pdf,
    export_txt,
)
from pipeline import PIPELINE_STEPS, PipelineResult, ReportMetadata, demo_recording, prepare_recording, run_pipeline
from transcription.base import TranscriptionOptions
from ui import components as ui
from ui.styles import APP_CSS
from ui.settings import app_api_key, app_models
from utils.audio import playback_mime
from utils.groq import check_model_connection

logger = logging.getLogger(__name__)

st.set_page_config(page_title=APP_NAME, page_icon="🛡️", layout="wide")
ui.inject_css(APP_CSS)


# ------------------------------------------------------------------ input section


def metadata_form() -> ReportMetadata:
    st.subheader("Case details")
    left, right = st.columns(2)
    case_reference = left.text_input("Case Reference", key="case_reference")
    officer = right.text_input("Officer", key="officer")
    date_value = left.date_input("Date", value=None, key="date")
    time_value = right.time_input("Time", value=None, key="time")
    location = st.text_input("Location", key="location")
    st.caption("Your entries take priority. Blank date, time or location fields may be filled from explicit statements in the recording and marked for review.")
    return ReportMetadata(
        case_reference=case_reference,
        officer=officer,
        date=date_value.isoformat() if date_value else "",
        time=time_value.strftime("%H:%M") if time_value else "",
        location=location,
    )


def engine_options() -> tuple[str, TranscriptionOptions]:
    st.subheader("Transcription")
    # Old provider selections must not survive the deployment migration.
    if st.session_state.get("engine") not in (None, ENGINE_GROQ, ENGINE_MOCK):
        st.session_state.pop("engine", None)
    engine = st.selectbox("Engine", options=[ENGINE_GROQ, ENGINE_MOCK],
                          format_func=ENGINE_LABELS.get, key="engine")
    options = TranscriptionOptions(with_speakers=False)
    if engine == ENGINE_GROQ:
        options.with_timestamps = st.checkbox("Segment timestamps", value=True, key="opt_ts")
        st.caption("Whisper transcribes in the original language. Speaker labels are unavailable; verify Hindi/Bhojpuri wording against the recording.")
        key = app_api_key()
        if not key:
            st.info("Set GROQ_API_KEY in .env or Streamlit Secrets to process audio. Create your key at https://console.groq.com/keys.")
        with st.expander("Groq connection and model settings"):
            models = app_models()
            st.write(f"Transcription: {models.transcription}. Report: {models.report}.")
            st.caption("Optional overrides: GROQ_TRANSCRIPTION_MODEL and GROQ_REPORT_MODEL. Groq Console controls model access and API limits.")
            st.caption("This check generates and validates a report from fictional text using the full report schema. Audio transcription needs a recording test.")
            if st.button("Test Groq connection", disabled=not key, key="check_groq"):
                try:
                    with st.spinner("Checking Groq…"):
                        check_model_connection(key, models)
                    st.success("Groq generated and validated a fictional report. Audio transcription has not been tested.")
                except UserFacingError as exc:
                    st.error(exc.user_message)
                except Exception as exc:
                    logger.error("Unexpected connection check error: %s", type(exc).__name__)
                    st.error("The connection check failed unexpectedly. No sensitive details are shown.")
    else:
        st.caption("Demo only: ignores the uploaded audio and uses a fictional transcript. Nothing is sent to Groq.")
    return engine, options


def upload_section() -> tuple[str, bytes] | None:
    st.subheader("Upload Recording")
    st.caption("Maximum 25 MB. Start with a short, non-sensitive WAV or MP3 recording.")
    uploaded = st.file_uploader(
        "Drag & drop a recording", type=list(SUPPORTED_EXTENSIONS), key="recording", accept_multiple_files=False
    )
    if uploaded is None:
        st.session_state.pop("prepared", None)
        return None
    data = uploaded.getvalue()
    prepared = st.session_state.get("prepared")
    if not prepared or prepared["file_id"] != uploaded.file_id:
        try:
            _mime, integrity, duration = prepare_recording(uploaded.name, data)
        except UserFacingError as exc:
            st.session_state.pop("prepared", None)
            st.error(exc.user_message)
            return None
        prepared = {"file_id": uploaded.file_id, "integrity": integrity, "duration": duration}
        st.session_state["prepared"] = prepared
    ui.render_integrity(prepared["integrity"], prepared["duration"])
    st.audio(data, format=playback_mime(uploaded.name))
    return uploaded.name, data


# ------------------------------------------------------------------ processing


def process(filename: str, data: bytes, engine: str, options: TranscriptionOptions, metadata: ReportMetadata) -> None:
    try:
        with st.status("Processing recording…", expanded=True) as status:
            result = run_pipeline(
                filename, data, engine, options, metadata, progress=lambda step: status.write(f"✓ {step}"),
                api_key=app_api_key() if engine != ENGINE_MOCK else None,
                models=app_models(),
            )
            status.update(label=f"Complete — {len(PIPELINE_STEPS)} steps finished", state="complete", expanded=False)
    except UserFacingError as exc:
        st.error(exc.user_message)
        return
    except Exception as exc:  # noqa: BLE001 - last-resort handler; never show internals
        logger.error("Unexpected pipeline error: %s", type(exc).__name__)
        st.error("An unexpected error occurred while processing the recording. No details are shown to protect sensitive data.")
        return
    st.session_state["result"] = result
    st.session_state["report_text"] = result.markdown
    st.session_state["officer_review"] = ""
    st.session_state["review_confirmed"] = False


def reset_report() -> None:
    """Clear the report, uploaded audio, metadata and review together before rerender."""
    for key in ("result", "prepared", "report_text", "officer_review", "review_confirmed",
                "recording", "case_reference", "officer", "date", "time", "location", "opt_ts", "opt_spk"):
        st.session_state.pop(key, None)


def invalidate_review() -> None:
    st.session_state["review_confirmed"] = False


# ------------------------------------------------------------------ results


def report_tab(result: PipelineResult) -> None:
    ui.draft_banner()
    ui.render_review_flags(result.report)
    st.markdown("**Edit the report below before export.** The warning banner is always re-added on export.")
    st.text_area("Report text (Markdown)", key="report_text", height=420, on_change=invalidate_review)
    st.text_area(
        "Officer Review / Corrections",
        key="officer_review",
        height=140,
        placeholder="Record corrections, additions and the reviewing officer's notes here.",
        on_change=invalidate_review,
    )
    reviewed = st.checkbox("I have checked this draft against the recording and reviewed the flagged items.", key="review_confirmed")
    document = compose_document(st.session_state["report_text"], st.session_state["officer_review"])
    with st.expander("Preview export"):
        st.markdown(document)
    st.markdown("#### Export")
    rid = result.integrity.recording_id
    cols = st.columns(4)
    if not reviewed:
        st.caption("Review the draft and confirm above to enable downloads. Exports remain marked as AI-generated drafts.")
    cols[0].download_button("Markdown (.md)", export_markdown(document), export_filename(rid, "md"), "text/markdown", disabled=not reviewed)
    cols[1].download_button("Text (.txt)", export_txt(document), export_filename(rid, "txt"), "text/plain", disabled=not reviewed)
    _export_button(cols[2], "Word (.docx)", export_docx, document, export_filename(rid, "docx"),
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document", disabled=not reviewed)
    _export_button(cols[3], "PDF (.pdf)", export_pdf, document, export_filename(rid, "pdf"), "application/pdf", disabled=not reviewed)


def _export_button(column, label: str, exporter, document: str, filename: str, mime: str, disabled: bool = False) -> None:  # noqa: ANN001
    try:
        column.download_button(label, exporter(document), filename, mime, disabled=disabled)
    except ExportError as exc:
        column.button(label, disabled=True, key=f"disabled_{label}")
        column.caption(exc.user_message)


def transcript_tab(result: PipelineResult) -> None:
    t = result.transcript
    st.markdown("### RAW TRANSCRIPT")
    st.caption("Exactly as returned by the transcription engine. It is never replaced by the AI summary.")
    for warning in t.warnings:
        st.warning(warning)
    if t.language_notes:
        st.info(f"Language notes: {t.language_notes}")
    st.text_area("Raw transcript", t.raw_transcript, height=320, disabled=True, label_visibility="collapsed")
    st.download_button("Download transcript.txt", t.raw_transcript.encode("utf-8"), "transcript.txt", "text/plain")
    if t.uncertainties:
        st.markdown("**Transcription uncertainties**")
        for note in t.uncertainties:
            st.markdown(f"- {note}")
    if any(s.speaker or s.start_time for s in t.segments):
        with st.expander("Segments (speaker / time)"):
            st.caption(f"Timestamp source: {t.timestamp_source}. Speaker labels are anonymous.")
            st.dataframe(
                [{"Speaker": s.speaker or "—", "Start": s.start_time or "—", "End": s.end_time or "—", "Text": s.text}
                 for s in t.segments],
                width="stretch",
            )


def metadata_tab(result: PipelineResult) -> None:
    ui.render_integrity(result.integrity, result.duration)
    meta = result.report.transcript_meta
    st.markdown("#### Processing")
    st.markdown(
        f"- **Engine:** {meta.engine}\n- **Transcription model:** {meta.model or 'n/a (local mock)'}\n"
        f"- **Report model:** {result.report_model or 'n/a (local mock)'}\n"
        f"- **Report output:** {'JSON compatibility mode + local validation' if result.report_format == 'json_object' else 'Strict JSON schema + local validation' if result.report_format == 'json_schema' else 'n/a (local mock)'}\n"
        f"- **Timestamp source:** {meta.timestamp_source}\n- **Speaker labels available:** {meta.speakers_available}"
    )


def results_section(current_recording_id: str | None) -> None:
    result: PipelineResult | None = st.session_state.get("result")
    if result is None:
        return
    st.divider()
    st.subheader(f"Documentation — {result.integrity.recording_id}")
    if result.transcript.engine == ENGINE_MOCK:
        st.info("FICTIONAL DEMO — this report comes from a built-in sample transcript, not an audio transcription.")
    if current_recording_id and current_recording_id != result.integrity.recording_id:
        st.warning("The results below belong to a previously processed recording, not the one currently uploaded.")
    tabs = st.tabs(["REPORT", "TRANSCRIPT", "TIMELINE", "STATEMENTS", "EVIDENCE", "METADATA"])
    with tabs[0]:
        report_tab(result)
    with tabs[1]:
        transcript_tab(result)
    with tabs[2]:
        ui.render_timeline(result.report)
    with tabs[3]:
        ui.render_statements(result.report)
    with tabs[4]:
        ui.render_evidence(result.report)
    with tabs[5]:
        metadata_tab(result)
    st.button("Start new report", on_click=reset_report)


def main() -> None:
    ui.render_header()
    st.caption("1. Add details  →  2. Choose a recording  →  3. Generate  →  4. Review and export")
    metadata = metadata_form()
    source = st.radio("Recording source", ["Upload audio", "Try fictional demo"],
                      index=0 if app_api_key() else 1, horizontal=True, key="source")
    if source == "Try fictional demo":
        engine, options = ENGINE_MOCK, TranscriptionOptions()
        st.info("Try the full review and export flow with a fictional Hindi/Bhojpuri transcript. No API key or upload is needed, and nothing is sent to Groq.")
        upload = demo_recording()
        _mime, integrity, duration = prepare_recording(*upload)
        st.session_state["prepared"] = {"file_id": "demo", "integrity": integrity, "duration": duration}
    else:
        engine, options = engine_options()
        upload = upload_section()
    ready = upload is not None and "prepared" in st.session_state and (engine == ENGINE_MOCK or bool(app_api_key()))
    label = "Generate demo report" if source == "Try fictional demo" else "Generate Police Documentation"
    if st.button(label, type="primary", disabled=not ready):
        filename, data = upload
        process(filename, data, engine, options, metadata)
    prepared = st.session_state.get("prepared")
    results_section(prepared["integrity"].recording_id if prepared else None)


main()
