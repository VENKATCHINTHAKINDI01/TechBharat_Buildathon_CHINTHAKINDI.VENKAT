"""Nexvi.Meets Pydantic schemas.

Source of truth for these shapes is ``docs/data-contracts.md`` at the repo
root. Any field added/changed here must be a deliberate, matching edit to
that document in the same change (AGENTS.md scope rule: "Do not modify
shared schemas silently").

These are Nexvi.Meets's own models -- distinct from Nexvi.Meets'
``app.models.meeting`` / ``app.models.action_item`` -- per
``docs/architecture.md``.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CandidateKind(str, Enum):
    decision = "decision"
    risk = "risk"
    blocker = "blocker"
    open_question = "open_question"
    action_item = "action_item"


class Classification(str, Enum):
    confirmed = "confirmed"
    suggestion = "suggestion"
    disputed = "disputed"
    rejected = "rejected"
    cancelled = "cancelled"


class OwnerResolutionMethod(str, Enum):
    exact_match = "exact_match"
    fuzzy_match = "fuzzy_match"
    unresolved = "unresolved"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class DateResolutionMethod(str, Enum):
    absolute = "absolute"
    relative = "relative"
    unresolved = "unresolved"


class AuditStage(str, Enum):
    ingestion = "ingestion"
    normalization = "normalization"
    extraction = "extraction"
    validation = "validation"
    resolution = "resolution"
    gate = "gate"
    review = "review"
    dedupe = "dedupe"
    # side effects -- one value per gated tool, so the audit log answers
    # "which external system did we touch" without parsing payloads.
    github_create = "github_create"
    calendar_create = "calendar_create"
    memory_index = "memory_index"
    notification = "notification"
    # orchestration
    agent_step = "agent_step"
    live = "live"


class SideEffect(str, Enum):
    """The external actions an approved item may fire. Every one is gated
    identically: passing GateDecision + explicit human ReviewDecision."""

    github_issue = "github_issue"
    calendar_invite = "calendar_invite"
    memory_index = "memory_index"
    notification = "notification"


class ReviewDecisionValue(str, Enum):
    approved = "approved"
    rejected = "rejected"
    edited_and_approved = "edited_and_approved"


class Participant(BaseModel):
    """One real meeting attendee. Owner resolution (F007) may only ever
    resolve to a participant already present in this directory -- it never
    invents one."""

    participant_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    email: Optional[str] = None


class TranscriptSegment(BaseModel):
    """One speaker turn.

    ``text`` is the original transcript text, verbatim, and is the ONLY
    thing evidence quotes are ever validated against. ``normalized_text``
    is an optional English rendering (Sarvam) used purely as extraction
    input to improve accuracy on code-switched speech.

    Keeping them separate is what lets Nexvi.Meets translate for
    comprehension without ever weakening the audit trail: a reviewer and
    a judge always see the words that were actually spoken.
    """

    segment_id: str
    speaker: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    text: str
    normalized_text: Optional[str] = None

    @property
    def extraction_text(self) -> str:
        """What the extractor reads. Falls back to the original when no
        normalization was performed."""
        return self.normalized_text or self.text


class EvidenceQuote(BaseModel):
    segment_id: str
    quote: str


class CandidateItem(BaseModel):
    candidate_id: str
    meeting_id: str
    kind: CandidateKind
    raw_text: str
    evidence_quotes: list[EvidenceQuote] = Field(default_factory=list)
    raw_owner_mention: Optional[str] = None
    raw_date_mention: Optional[str] = None
    priority: Priority = Priority.medium
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("evidence_quotes")
    @classmethod
    def action_items_need_evidence(cls, v, info):
        # Structural check only (non-empty list required at the schema
        # level for action_item); the *content* check (quote is a verbatim
        # substring of the segment) lives in F005's extractor, since that
        # requires the transcript, which this schema does not carry.
        kind = info.data.get("kind")
        if kind == CandidateKind.action_item and not v:
            raise ValueError("action_item candidates must carry at least one evidence_quote")
        return v


class ValidatedItem(CandidateItem):
    classification: Classification
    contradiction_of: Optional[str] = None
    contradiction_note: Optional[str] = None


class ResolvedItem(ValidatedItem):
    """A validated item with owner and date resolved.

    ``confidence`` on this class is the **composite** score (extraction
    blended with owner- and date-resolution outcomes -- see
    ``app/services/confidence.py``), because that is what the safety gate
    compares against the threshold. ``extraction_confidence`` preserves
    the model's original self-reported number so the composite can be
    recomputed when a reviewer edits the owner or the date.
    """

    extraction_confidence: Optional[float] = None
    owner_participant_id: Optional[str] = None
    owner_resolution_method: OwnerResolutionMethod = OwnerResolutionMethod.unresolved
    due_date: Optional[date] = None
    date_resolution_method: DateResolutionMethod = DateResolutionMethod.unresolved


class GateDecision(BaseModel):
    candidate_id: str
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime


class ReviewDecision(BaseModel):
    candidate_id: str
    reviewer: str
    decision: ReviewDecisionValue
    final_payload: Optional[dict] = None
    decided_at: datetime

    @field_validator("final_payload")
    @classmethod
    def approved_needs_payload(cls, v, info):
        decision = info.data.get("decision")
        if decision in (ReviewDecisionValue.approved, ReviewDecisionValue.edited_and_approved) and v is None:
            raise ValueError("final_payload is required when decision is approved or edited_and_approved")
        return v


class AuditEvent(BaseModel):
    event_id: str
    meeting_id: str
    candidate_id: Optional[str] = None
    stage: AuditStage
    payload: dict
    created_at: datetime


class MeetingRecord(BaseModel):
    """F011b: aggregates a meeting's ResolvedItems into the structured
    record the TechBharat brief requires (executive summary + decisions +
    open questions + risks/blockers + action items). See
    docs/data-contracts.md for the partition invariant this must satisfy."""

    meeting_id: str
    executive_summary: str
    decisions: list[ResolvedItem] = Field(default_factory=list)
    open_questions: list[ResolvedItem] = Field(default_factory=list)
    risks_blockers: list[ResolvedItem] = Field(default_factory=list)
    action_items: list[ResolvedItem] = Field(default_factory=list)
    generated_at: datetime


class GitHubIssueRecord(BaseModel):
    dedupe_key: str
    candidate_id: str
    meeting_id: str
    github_issue_number: int
    github_issue_url: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Orchestration + side-effect records
# ---------------------------------------------------------------------------


class AgentStatus(str, Enum):
    ok = "ok"
    skipped = "skipped"
    failed = "failed"
    interrupted = "interrupted"


class AgentStep(BaseModel):
    """One agent's execution within a run.

    Persisted and shown in the UI so 'what did the agent system actually
    do' is inspectable rather than a black box -- the brief judges an
    agent on its auditability, not on it feeling autonomous.
    """

    agent: str
    status: AgentStatus
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    tools_used: list[str] = Field(default_factory=list)
    summary: str = ""
    error: Optional[str] = None


class AgentRun(BaseModel):
    run_id: str
    meeting_id: str
    steps: list[AgentStep] = Field(default_factory=list)
    runtime: str = "inhouse"  # "inhouse" | "langgraph"
    interrupted_at: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None

    @property
    def total_ms(self) -> int:
        return sum(s.duration_ms for s in self.steps)


class CalendarEventRecord(BaseModel):
    dedupe_key: str
    candidate_id: str
    meeting_id: str
    event_id: str
    attendee_email: str
    due_date: Optional[date] = None
    created_at: datetime


class NotificationRecord(BaseModel):
    notification_id: str
    candidate_id: str
    meeting_id: str
    owner_email: str
    channel: str = "calendar"
    reminder_at: Optional[datetime] = None
    created_at: datetime


class MemoryRecord(BaseModel):
    """An approved commitment indexed for cross-meeting recall.

    Only approved items are ever indexed -- the memory store is a record
    of what a team actually committed to, never of what a model guessed.
    """

    memory_id: str
    candidate_id: str
    meeting_id: str
    meeting_title: str
    meeting_date: str
    text: str
    owner_participant_id: Optional[str] = None
    due_date: Optional[date] = None
    created_at: datetime


class CarriedForwardItem(BaseModel):
    """A prior-meeting commitment surfaced in a later meeting."""

    memory: MemoryRecord
    similarity: float
    days_overdue: Optional[int] = None
