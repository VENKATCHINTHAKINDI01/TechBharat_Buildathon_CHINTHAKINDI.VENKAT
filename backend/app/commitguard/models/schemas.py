"""CommitGuard Pydantic schemas.

Source of truth for these shapes is ``docs/data-contracts.md`` at the repo
root. Any field added/changed here must be a deliberate, matching edit to
that document in the same change (AGENTS.md scope rule: "Do not modify
shared schemas silently").

These are CommitGuard's own models -- distinct from Nexvi.Meets'
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


class DateResolutionMethod(str, Enum):
    absolute = "absolute"
    relative = "relative"
    unresolved = "unresolved"


class AuditStage(str, Enum):
    ingestion = "ingestion"
    extraction = "extraction"
    validation = "validation"
    resolution = "resolution"
    gate = "gate"
    review = "review"
    github_create = "github_create"
    dedupe = "dedupe"


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
    segment_id: str
    speaker: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    text: str


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


class GitHubIssueRecord(BaseModel):
    dedupe_key: str
    candidate_id: str
    github_issue_number: int
    github_issue_url: str
    created_at: datetime
