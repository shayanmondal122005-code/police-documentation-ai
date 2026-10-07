"""Pydantic schemas for the structured police field-interaction report.

`ModelReport` is what the language model must produce (and what Groq's JSON-schema
mode is given). `PoliceReport` wraps it with administrative data, integrity data and
review flags that are filled in by code, never by the model.

Every extracted item carries a `SourceRef` so it can later be linked back to an exact
position in the recording. Times are strings or None; None means "not available".
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from config import AI_DRAFT_WARNING, REPORT_TITLE

UNKNOWN_PERSON = "Unknown Person"
UNKNOWN_SPEAKER = "Unknown speaker"
NOT_PROVIDED = "Not provided"


class StatementType(str, Enum):
    FACT = "fact"
    ALLEGATION = "allegation"
    OPINION = "opinion"
    BELIEF = "belief"
    HEARSAY = "hearsay"
    UNCERTAINTY = "uncertainty"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PurposeBasis(str, Enum):
    STATED = "directly stated"
    INFERRED = "inferred"
    UNCLEAR = "unclear from recording"


class EvidenceCategory(str, Enum):
    CCTV = "CCTV"
    MOBILE_PHONE = "mobile phone"
    PHONE_NUMBER = "phone number"
    VEHICLE = "vehicle"
    VEHICLE_REGISTRATION = "vehicle registration"
    DOCUMENT = "document"
    WEAPON = "weapon"
    OBJECT = "object"
    LOCATION = "location"
    OTHER_RECORDING = "other recording"
    DIGITAL_EVIDENCE = "digital evidence"
    PHOTOGRAPH = "photograph"
    MESSAGE = "message"
    COMPUTER = "computer"
    OTHER = "other"


class UncertaintyKind(str, Enum):
    UNCLEAR_SPEECH = "unclear speech"
    UNCERTAIN_NAME = "uncertain name"
    UNINTELLIGIBLE = "unintelligible section"
    AMBIGUOUS = "ambiguous statement"
    POOR_AUDIO = "poor audio"
    OVERLAPPING_SPEECH = "overlapping speech"
    TIMESTAMP = "uncertain timestamp"
    LANGUAGE = "language uncertainty"


class SourceRef(BaseModel):
    """Pointer from an extracted item back to the transcript/recording."""

    source_type: Literal["transcript"] = "transcript"
    start_time: str | None = Field(None, description="Only if a time marker for this item exists in the transcript; else null.")
    end_time: str | None = Field(None, description="Only if a time marker for this item exists in the transcript; else null.")
    quote: str | None = Field(None, description="Exact excerpt copied character-for-character from the transcript.")
    quote_verified: bool | None = Field(None, description="Always leave null. Set by the system after checking the quote.")


class Purpose(BaseModel):
    stated_purpose: str | None = Field(None, description="Purpose explicitly stated in the recording, else null.")
    inferred_purpose: str | None = Field(None, description="Apparent purpose inferred from context, else null. Must be hedged.")
    basis: PurposeBasis = PurposeBasis.UNCLEAR


class Person(BaseModel):
    name: str = UNKNOWN_PERSON
    role: str | None = Field(None, description="Role only if stated in the recording (e.g. officer, complainant). Never guess.")
    relevant_info: str | None = None
    source: SourceRef | None = None

    @field_validator("name")
    @classmethod
    def _default_name(cls, value: str) -> str:
        return value.strip() or UNKNOWN_PERSON


class TimelineEvent(BaseModel):
    order: int = Field(..., ge=1, description="1-based chronological order.")
    description: str
    source: SourceRef | None = None


class Statement(BaseModel):
    speaker: str = UNKNOWN_SPEAKER
    statement: str
    classification: StatementType
    source: SourceRef | None = None

    @field_validator("speaker")
    @classmethod
    def _default_speaker(cls, value: str) -> str:
        return value.strip() or UNKNOWN_SPEAKER


class StatedFact(BaseModel):
    """A fact that the recording itself states, with who stated it."""

    text: str
    stated_by: str = UNKNOWN_SPEAKER
    source: SourceRef | None = None


class Allegation(BaseModel):
    """An allegation or claim. `claim` is its content; attribution is added when rendered."""

    alleged_by: str = UNKNOWN_SPEAKER
    claim: str = Field(..., description='Content of the allegation, e.g. "Rahul took the phone". Do not state it as fact.')
    source: SourceRef | None = None

    def attributed_text(self) -> str:
        """Sentence that always preserves attribution."""
        return f"{self.alleged_by} alleged that {self.claim.rstrip('.')}."


class Contradiction(BaseModel):
    statement_a: str
    statement_b: str
    speakers: list[str] = Field(default_factory=list)
    why_may_conflict: str
    source_a: SourceRef | None = None
    source_b: SourceRef | None = None
    confidence: Confidence = Confidence.LOW
    qualification: str | None = Field(None, description="Ways the statements might be reconciled, if any.")

    @model_validator(mode="after")
    def _require_two_distinct_statements(self) -> "Contradiction":
        a, b = self.statement_a.strip(), self.statement_b.strip()
        if not a or not b or not self.why_may_conflict.strip():
            raise ValueError("A potential inconsistency needs two statements and a reason.")
        if a.casefold() == b.casefold():
            raise ValueError("A potential inconsistency needs two different statements.")
        return self


class EvidenceItem(BaseModel):
    category: EvidenceCategory
    description: str
    mentioned_by: str | None = None
    source: SourceRef | None = None


class FollowUp(BaseModel):
    action: str
    basis: str = Field(..., description="What in the recording this follow-up is based on.")


class UncertaintyNote(BaseModel):
    kind: UncertaintyKind
    description: str
    source: SourceRef | None = None


class DetectedMetadata(BaseModel):
    """Administrative details explicitly stated in the recording (never guessed)."""

    date: str | None = None
    time: str | None = None
    location: str | None = None


class ModelReport(BaseModel):
    """The analysis produced by the language model."""

    purpose: Purpose
    executive_summary: str
    persons: list[Person] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    statements: list[Statement] = Field(default_factory=list)
    explicit_facts: list[StatedFact] = Field(default_factory=list)
    allegations: list[Allegation] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    follow_up_actions: list[FollowUp] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    uncertainties: list[UncertaintyNote] = Field(default_factory=list)
    detected_metadata: DetectedMetadata = Field(default_factory=DetectedMetadata)


class AdministrativeInfo(BaseModel):
    """Administrative block. User-entered values always win over values found in the recording."""

    case_reference: str | None = None
    officer: str | None = None
    date: str | None = None
    time: str | None = None
    location: str | None = None
    recording_filename: str
    recording_duration: str = "Unavailable"
    recording_id: str
    sha256: str
    processing_timestamp: str
    fields_from_recording: list[str] = Field(default_factory=list)


class TranscriptMeta(BaseModel):
    """How the transcript was produced; shown in the report so reviewers know its limits."""

    engine: str
    model: str | None = None
    timestamp_source: str = "none"
    speakers_available: bool = False
    language_notes: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PoliceReport(BaseModel):
    """Final structured report object."""

    title: str = REPORT_TITLE
    ai_draft_warning: str = AI_DRAFT_WARNING
    admin: AdministrativeInfo
    analysis: ModelReport
    transcript_meta: TranscriptMeta
    review_flags: list[str] = Field(default_factory=list)
