"""Request/response DTOs for the HTTP layer.

Kept separate from ``app/domain/models.py`` on purpose: the domain models
are the contract the pipeline and safety gate share, and they must not
change shape just because an HTTP client wants a field flattened or a
label renamed.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.adapters.trackers.base import IssuePayload
from app.domain.models import MeetingRecord, Priority, ResolvedItem


class ParticipantIn(BaseModel):
    participant_id: Optional[str] = None
    name: str
    aliases: list[str] = Field(default_factory=list)
    email: Optional[str] = None
    github_login: Optional[str] = None


class UploadResponse(BaseModel):
    meeting_id: str
    title: str
    segments: int
    candidates: int
    eligible: int
    extractor_used: str
    fallback_reason: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class GateView(BaseModel):
    eligible: bool
    reasons: list[str]


class CandidateView(BaseModel):
    """One reviewable candidate, with everything the reviewer needs to
    judge it: the evidence, the gate verdict, and the exact payload that
    would be sent if they approve."""

    candidate_id: str
    meeting_id: str
    kind: str
    classification: str
    raw_text: str
    owner_participant_id: Optional[str]
    owner_name: Optional[str]
    owner_resolution_method: str
    due_date: Optional[date]
    date_resolution_method: str
    priority: Priority
    confidence: float
    contradiction_note: Optional[str]
    evidence: list[dict]
    gate: GateView
    review_status: Optional[str] = None
    issue_url: Optional[str] = None
    proposed_payload: Optional[IssuePayload] = None


class MeetingDetailResponse(BaseModel):
    meeting_id: str
    title: str
    meeting_date: str
    participants: list[dict]
    record: Optional[MeetingRecord]
    candidates: list[CandidateView]


class ApproveRequest(BaseModel):
    reviewer: str = "demo_reviewer"
    payload: Optional[IssuePayload] = None  # present => reviewer edited it
    # Which gated side effects to fire. Defaults to GitHub only; opting
    # into more is always an explicit per-approval choice.
    effects: Optional[list[str]] = None


class ApproveResponse(BaseModel):
    candidate_id: str
    created: bool
    duplicate_suppressed: bool
    issue_number: Optional[int]
    issue_url: Optional[str]
    dedupe_key: str
    effects: list[dict] = Field(default_factory=list)


class RejectRequest(BaseModel):
    reviewer: str = "demo_reviewer"
    reason: Optional[str] = None


class EditRequest(BaseModel):
    """Edits are applied to the *item*, then the payload is rebuilt from
    it, so the reviewer can never approve a payload that disagrees with
    the item the gate evaluated."""

    reviewer: str = "demo_reviewer"
    raw_text: Optional[str] = None
    owner_participant_id: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[Priority] = None


class AuditEventView(BaseModel):
    event_id: str
    meeting_id: str
    candidate_id: Optional[str]
    stage: str
    payload: dict
    created_at: datetime


def to_candidate_view(
    item: ResolvedItem,
    gate,
    owner_name: Optional[str],
    payload: Optional[IssuePayload],
    review_status: Optional[str],
    issue_url: Optional[str],
) -> CandidateView:
    return CandidateView(
        candidate_id=item.candidate_id,
        meeting_id=item.meeting_id,
        kind=item.kind.value,
        classification=item.classification.value,
        raw_text=item.raw_text,
        owner_participant_id=item.owner_participant_id,
        owner_name=owner_name,
        owner_resolution_method=item.owner_resolution_method.value,
        due_date=item.due_date,
        date_resolution_method=item.date_resolution_method.value,
        priority=item.priority,
        confidence=item.confidence,
        contradiction_note=item.contradiction_note,
        evidence=[q.model_dump() for q in item.evidence_quotes],
        gate=GateView(eligible=gate.eligible, reasons=gate.reasons),
        review_status=review_status,
        issue_url=issue_url,
        proposed_payload=payload,
    )
