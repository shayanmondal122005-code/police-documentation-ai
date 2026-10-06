"""Deterministic checks applied to model output after schema validation.

The model is not trusted. Code verifies quotes against the transcript, strips timestamps
the transcript cannot support, re-classifies hedged "facts", and flags prohibited language.
All checks are conservative heuristics: they raise flags for the reviewing officer rather
than silently rewriting meaning. They are not a substitute for human review.
"""

from __future__ import annotations

import re
import unicodedata

from documentation.schemas import (
    ModelReport,
    SourceRef,
    Statement,
    StatementType,
)
from transcription.base import TranscriptResult

# Phrases that signal belief/speculation (English, Hindi, Bhojpuri). Heuristic, not exhaustive.
BELIEF_MARKERS = (
    "i think", "i believe", "i guess", "maybe", "perhaps", "probably", "seems", "apparently",
    "मुझे लगता", "लगता है", "शायद", "सायद", "लागेला", "लागता", "बुझाता", "बुझाला",
)
# Phrases that signal the speaker is relaying what someone else said.
HEARSAY_MARKERS = (
    "i heard", "they say", "people say", "told me", "someone said",
    "सुना है", "सुना कि", "लोग कहते", "कहते हैं", "बताया कि", "सुनले", "सुनली",
)
# Language the report must never use (guilt, lying, confession, criminal intent as fact).
PROHIBITED_PATTERNS = (
    r"\blied\b", r"\blying\b", r"\bliar\b", r"\bguilty\b", r"\binnocent\b",
    r"\bconfess(?:ed|ion)?\b", r"\bculprit\b", r"\bperpetrator\b", r"\bcommitted the\b",
    r"\bcriminal intent\b",
)


def normalise_for_match(text: str) -> str:
    """Normalise text for tolerant quote matching: NFC, casefold, no punctuation, single spaces."""
    text = unicodedata.normalize("NFC", text).casefold()
    text = "".join(" " if unicodedata.category(c).startswith(("P", "S")) else c for c in text)
    return " ".join(text.split())


def _iter_sources(analysis: ModelReport) -> list[SourceRef]:
    refs: list[SourceRef | None] = []
    refs += [p.source for p in analysis.persons]
    refs += [e.source for e in analysis.timeline]
    refs += [s.source for s in analysis.statements]
    refs += [f.source for f in analysis.explicit_facts]
    refs += [a.source for a in analysis.allegations]
    for c in analysis.contradictions:
        refs += [c.source_a, c.source_b]
    refs += [e.source for e in analysis.evidence]
    refs += [u.source for u in analysis.uncertainties]
    return [r for r in refs if r is not None]


def verify_quotes(analysis: ModelReport, transcript: TranscriptResult) -> int:
    """Set `quote_verified` on every source; return the count of unverifiable quotes."""
    haystack = normalise_for_match(transcript.raw_transcript)
    unverified = 0
    for ref in _iter_sources(analysis):
        if not ref.quote or not ref.quote.strip():
            ref.quote_verified = None
            continue
        ref.quote_verified = normalise_for_match(ref.quote) in haystack
        unverified += 0 if ref.quote_verified else 1
    return unverified


def enforce_timestamp_policy(analysis: ModelReport, transcript: TranscriptResult) -> bool:
    """Remove all report timestamps when the transcript has none. Return True if any were removed."""
    if transcript.timestamps_available:
        return False
    removed = False
    for ref in _iter_sources(analysis):
        if ref.start_time or ref.end_time:
            ref.start_time = ref.end_time = None
            removed = True
    return removed


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    folded = normalise_for_match(text)
    return any(normalise_for_match(m) in folded for m in markers)


def _hedged_type(*texts: str) -> StatementType | None:
    combined = " ".join(t for t in texts if t)
    if _contains_marker(combined, HEARSAY_MARKERS):
        return StatementType.HEARSAY
    if _contains_marker(combined, BELIEF_MARKERS):
        return StatementType.BELIEF
    return None


def downgrade_hedged_facts(analysis: ModelReport) -> list[str]:
    """Never let hedged speech stand as fact.

    Statements classified `fact` whose text/quote carries belief or hearsay markers are
    re-classified. Items in `explicit_facts` with such markers are moved into `statements`.
    Returns human-readable flags describing every change.
    """
    flags: list[str] = []
    for stmt in analysis.statements:
        if stmt.classification is not StatementType.FACT:
            continue
        hedged = _hedged_type(stmt.statement, stmt.source.quote if stmt.source else "")
        if hedged:
            stmt.classification = hedged
            flags.append(
                f"Statement by {stmt.speaker} was re-classified from fact to {hedged.value} "
                "because the speech contains hedging language."
            )
    kept = []
    for fact in analysis.explicit_facts:
        hedged = _hedged_type(fact.text, fact.source.quote if fact.source else "")
        if hedged:
            analysis.statements.append(
                Statement(speaker=fact.stated_by, statement=fact.text, classification=hedged, source=fact.source)
            )
            flags.append(
                f"An item listed as a fact by {fact.stated_by} was moved to Important Statements "
                f"as {hedged.value} because the speech contains hedging language."
            )
        else:
            kept.append(fact)
    analysis.explicit_facts = kept
    return flags


def find_prohibited_language(text: str) -> list[str]:
    """Return prohibited terms found in `text` (guilt/lying/confession language)."""
    found = []
    for pattern in PROHIBITED_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            found.append(match.group(0).lower())
    return found


def analysis_text(analysis: ModelReport) -> str:
    """All model-written free text in one string, for prohibited-language scanning."""
    chunks = [analysis.executive_summary, analysis.purpose.stated_purpose or "", analysis.purpose.inferred_purpose or ""]
    chunks += [p.relevant_info or "" for p in analysis.persons]
    chunks += [e.description for e in analysis.timeline]
    chunks += [f.text for f in analysis.explicit_facts]
    chunks += [a.claim for a in analysis.allegations]
    chunks += [f"{c.why_may_conflict} {c.qualification or ''}" for c in analysis.contradictions]
    chunks += analysis.unresolved_questions
    chunks += [f.action for f in analysis.follow_up_actions]
    chunks += [e.description for e in analysis.evidence]
    return "\n".join(chunks)


def run_guardrails(analysis: ModelReport, transcript: TranscriptResult) -> list[str]:
    """Apply all checks in place and return review flags for the officer."""
    flags: list[str] = []
    if enforce_timestamp_policy(analysis, transcript):
        flags.append(
            "The model returned timestamps although the transcript has none; they were removed."
        )
    flags += downgrade_hedged_facts(analysis)
    unverified = verify_quotes(analysis, transcript)
    if unverified:
        flags.append(
            f"{unverified} source quote(s) could not be found in the transcript and are marked "
            "'unverified'. Check them against the recording."
        )
    terms = find_prohibited_language(analysis_text(analysis))
    if terms:
        flags.append(
            "The draft contains language that should not appear in a neutral report ("
            + ", ".join(sorted(set(terms)))
            + "). Review and rewrite those passages."
        )
    return flags
