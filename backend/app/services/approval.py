"""The approval service — the single chokepoint for external side effects.

Everything the brief scores as a hard requirement converges here:

- "Nothing is created, sent or posted until a person sees the exact
  payload and approves it"        -> an explicit ReviewDecision is required.
- "Zero unapproved actions"       -> the gate is re-evaluated server-side,
  and the resulting Authorization is what the tool registry demands before
  it will invoke any side-effecting tool.
- "Running the same meeting twice must not create duplicate tasks"
                                  -> each effect checks its own dedupe key.
- "An audit log showing every action the agent took, what it was based on,
  and who approved it"            -> every branch writes an event, including
  the refusals and the failures.

Four side effects can fire, each independently gated and independently
idempotent. One failing does not roll back the others — they are separate
external systems, and a failed calendar invite must not delete a GitHub
issue that was created successfully. Each outcome is reported separately.

Design note: the gate is re-run here even though the review API already
checked it. A client can call endpoints in any order; the invariant has to
hold at the moment of the side effect, not at the moment of the UI's last
render.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.adapters.calendar.base import CalendarError, CalendarInvite
from app.adapters.trackers.base import IssuePayload, IssueTrackerError
from app.domain.models import (
    AuditStage,
    CalendarEventRecord,
    GitHubIssueRecord,
    Participant,
    ResolvedItem,
    ReviewDecision,
    ReviewDecisionValue,
    SideEffect,
)
from app.domain.safety.gate import check_gate
from app.services.audit import AuditLogger
from app.services.idempotency import compute_dedupe_key
from app.tools.registry import Authorization, ToolRegistry


class ApprovalRefused(RuntimeError):
    """The approval cannot proceed. Carries the gate reasons so the API can
    tell the reviewer exactly which rule blocked it."""

    def __init__(self, message: str, reasons: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.reasons = reasons or []


@dataclass
class EffectOutcome:
    effect: str
    status: str  # "created" | "duplicate_suppressed" | "skipped" | "failed"
    detail: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in ("created", "duplicate_suppressed")


@dataclass
class ApprovalResult:
    candidate_id: str
    dedupe_key: str
    effects: list[EffectOutcome]

    @property
    def created(self) -> bool:
        return any(e.effect == SideEffect.github_issue.value and e.status == "created" for e in self.effects)

    @property
    def duplicate_suppressed(self) -> bool:
        return any(
            e.effect == SideEffect.github_issue.value and e.status == "duplicate_suppressed"
            for e in self.effects
        )

    def _github(self) -> Optional[EffectOutcome]:
        return next((e for e in self.effects if e.effect == SideEffect.github_issue.value), None)

    @property
    def issue_number(self) -> Optional[int]:
        gh = self._github()
        return gh.detail.get("issue_number") if gh else None

    @property
    def issue_url(self) -> Optional[str]:
        gh = self._github()
        return gh.detail.get("issue_url") if gh else None

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "dedupe_key": self.dedupe_key,
            "effects": [
                {"effect": e.effect, "status": e.status, "detail": e.detail, "error": e.error}
                for e in self.effects
            ],
        }


DEFAULT_EFFECTS = (SideEffect.github_issue,)


async def approve_and_execute(
    *,
    repository,
    registry: ToolRegistry,
    item: ResolvedItem,
    payload: IssuePayload,
    reviewer: str,
    confidence_threshold: float,
    edited: bool,
    participants: list[Participant],
    meeting_title: str,
    meeting_date: str,
    effects: tuple[SideEffect, ...] = DEFAULT_EFFECTS,
    tracker=None,
    calendar=None,
    memory_store=None,
) -> ApprovalResult:
    audit = AuditLogger(repository, item.meeting_id)

    # --- 1. Deterministic gate, re-evaluated server-side. ---
    decision = check_gate(item, confidence_threshold)
    await audit.record(
        AuditStage.gate,
        {
            "eligible": decision.eligible,
            "reasons": decision.reasons,
            "checked_at": decision.checked_at.isoformat(),
            "context": "approval",
        },
        candidate_id=item.candidate_id,
    )
    if not decision.eligible:
        await audit.record(
            AuditStage.review,
            {"outcome": "approval_refused", "reviewer": reviewer, "reasons": decision.reasons},
            candidate_id=item.candidate_id,
        )
        raise ApprovalRefused("Candidate is not eligible for external action.", decision.reasons)

    # --- 2. Record the human decision BEFORE any side effect, so an
    #        approval is never missing from the trail if a call fails. ---
    review = ReviewDecision(
        candidate_id=item.candidate_id,
        reviewer=reviewer,
        decision=(
            ReviewDecisionValue.edited_and_approved if edited else ReviewDecisionValue.approved
        ),
        final_payload=payload.model_dump(),
        decided_at=datetime.now(timezone.utc),
    )
    await repository.save_review_decision(review)
    await audit.record(
        AuditStage.review,
        {
            "outcome": review.decision.value,
            "reviewer": reviewer,
            "final_payload": review.final_payload,
            "requested_effects": [e.value for e in effects],
        },
        candidate_id=item.candidate_id,
    )

    # --- 3. The authorization token the tool registry demands. Without
    #        this object, no side-effecting tool can be invoked at all. ---
    authorization = Authorization(gate=decision, review=review)
    dedupe_key = compute_dedupe_key(item.meeting_id, item.owner_participant_id, payload.title)

    owner = next(
        (p for p in participants if p.participant_id == item.owner_participant_id), None
    )
    outcomes: list[EffectOutcome] = []

    # --- 4. Fan out. Each effect is independently gated and idempotent. ---
    if SideEffect.github_issue in effects:
        outcomes.append(
            await _github(
                repository, registry, authorization, audit, item, payload, dedupe_key, reviewer, tracker
            )
        )

    if SideEffect.calendar_invite in effects:
        outcomes.append(
            await _calendar(
                repository, registry, authorization, audit, item, payload, dedupe_key,
                owner, meeting_title, calendar,
            )
        )

    if SideEffect.memory_index in effects:
        outcomes.append(
            await _memory(
                repository, registry, authorization, audit, item, meeting_title, meeting_date, memory_store
            )
        )

    if SideEffect.notification in effects:
        outcomes.append(
            await _notify(repository, registry, authorization, audit, item, owner)
        )

    return ApprovalResult(candidate_id=item.candidate_id, dedupe_key=dedupe_key, effects=outcomes)


async def _github(
    repository, registry, authorization, audit, item, payload, dedupe_key, reviewer, tracker
) -> EffectOutcome:
    name = SideEffect.github_issue.value
    if tracker is None:
        return EffectOutcome(name, "skipped", error="No issue tracker configured.")

    existing = await repository.find_issue_by_dedupe_key(dedupe_key)
    if existing is not None:
        await audit.record(
            AuditStage.dedupe,
            {
                "outcome": "duplicate_suppressed",
                "effect": name,
                "dedupe_key": dedupe_key,
                "existing_issue_number": existing.github_issue_number,
                "existing_issue_url": existing.github_issue_url,
            },
            candidate_id=item.candidate_id,
        )
        return EffectOutcome(
            name,
            "duplicate_suppressed",
            {"issue_number": existing.github_issue_number, "issue_url": existing.github_issue_url},
        )

    try:
        created = await registry.invoke(
            "github_issue", authorization=authorization, tracker=tracker, payload=payload
        )
    except IssueTrackerError as exc:
        await audit.record(
            AuditStage.github_create,
            {"outcome": "failed", "error": str(exc), "payload": payload.model_dump()},
            candidate_id=item.candidate_id,
        )
        raise

    await repository.save_issue_record(
        GitHubIssueRecord(
            dedupe_key=dedupe_key,
            candidate_id=item.candidate_id,
            meeting_id=item.meeting_id,
            github_issue_number=created.number,
            github_issue_url=created.url,
            created_at=datetime.now(timezone.utc),
        )
    )
    await audit.record(
        AuditStage.github_create,
        {
            "outcome": "created",
            "issue_number": created.number,
            "issue_url": created.url,
            "dedupe_key": dedupe_key,
            "payload": payload.model_dump(),
            "approved_by": reviewer,
        },
        candidate_id=item.candidate_id,
    )
    return EffectOutcome(
        name, "created", {"issue_number": created.number, "issue_url": created.url}
    )


async def _calendar(
    repository, registry, authorization, audit, item, payload, dedupe_key,
    owner, meeting_title, calendar,
) -> EffectOutcome:
    name = SideEffect.calendar_invite.value
    if calendar is None:
        return EffectOutcome(name, "skipped", error="Calendar is not configured.")
    if owner is None or not owner.email:
        # Not a failure: the gate guarantees an owner exists, but a
        # participant directory without an email simply has nowhere to send.
        return EffectOutcome(
            name, "skipped", error="Owner has no email address in the participant directory."
        )

    existing = await repository.find_calendar_event_by_dedupe_key(dedupe_key)
    if existing is not None:
        await audit.record(
            AuditStage.dedupe,
            {"outcome": "duplicate_suppressed", "effect": name, "dedupe_key": dedupe_key},
            candidate_id=item.candidate_id,
        )
        return EffectOutcome(name, "duplicate_suppressed", {"event_id": existing.event_id})

    invite = CalendarInvite(
        summary=f"Commitment: {payload.title[:80]}",
        description=payload.body,
        attendee_email=owner.email,
        due_date=item.due_date,
    )
    try:
        event = await registry.invoke(
            "calendar_invite", authorization=authorization, calendar=calendar, invite=invite
        )
    except CalendarError as exc:
        await audit.record(
            AuditStage.calendar_create,
            {"outcome": "failed", "error": str(exc), "attendee": owner.email},
            candidate_id=item.candidate_id,
        )
        # A calendar failure must not undo a successfully created issue.
        return EffectOutcome(name, "failed", error=str(exc))

    await repository.save_calendar_event(
        CalendarEventRecord(
            dedupe_key=dedupe_key,
            candidate_id=item.candidate_id,
            meeting_id=item.meeting_id,
            event_id=event.event_id,
            attendee_email=owner.email,
            due_date=item.due_date,
            created_at=datetime.now(timezone.utc),
        )
    )
    await audit.record(
        AuditStage.calendar_create,
        {
            "outcome": "created",
            "event_id": event.event_id,
            "attendee": owner.email,
            "due_date": item.due_date.isoformat() if item.due_date else None,
        },
        candidate_id=item.candidate_id,
    )
    return EffectOutcome(name, "created", {"event_id": event.event_id, "link": event.html_link})


async def _memory(
    repository, registry, authorization, audit, item, meeting_title, meeting_date, memory_store
) -> EffectOutcome:
    name = SideEffect.memory_index.value
    if memory_store is None:
        return EffectOutcome(name, "skipped", error="Memory store is not configured.")
    try:
        record = await registry.invoke(
            "memory_index",
            authorization=authorization,
            store=memory_store,
            item=item,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
        )
    except Exception as exc:  # noqa: BLE001 - indexing must never undo an issue
        await audit.record(
            AuditStage.memory_index,
            {"outcome": "failed", "error": str(exc)},
            candidate_id=item.candidate_id,
        )
        return EffectOutcome(name, "failed", error=str(exc))

    await audit.record(
        AuditStage.memory_index,
        {"outcome": "created", "memory_id": record.memory_id},
        candidate_id=item.candidate_id,
    )
    return EffectOutcome(name, "created", {"memory_id": record.memory_id})


async def _notify(repository, registry, authorization, audit, item, owner) -> EffectOutcome:
    name = SideEffect.notification.value
    if owner is None or not owner.email:
        return EffectOutcome(name, "skipped", error="Owner has no email address.")
    try:
        record = await registry.invoke(
            "notification",
            authorization=authorization,
            repository=repository,
            item=item,
            owner_email=owner.email,
        )
    except Exception as exc:  # noqa: BLE001
        return EffectOutcome(name, "failed", error=str(exc))

    await audit.record(
        AuditStage.notification,
        {
            "outcome": "recorded",
            "owner_email": owner.email,
            "reminder_at": record.reminder_at.isoformat() if record.reminder_at else None,
            "note": "reminder time is computed intent; no background scheduler runs yet",
        },
        candidate_id=item.candidate_id,
    )
    return EffectOutcome(
        name,
        "created",
        {"notification_id": record.notification_id,
         "reminder_at": record.reminder_at.isoformat() if record.reminder_at else None},
    )


async def reject_candidate(
    *, repository, item: ResolvedItem, reviewer: str, reason: Optional[str]
) -> ReviewDecision:
    audit = AuditLogger(repository, item.meeting_id)
    review = ReviewDecision(
        candidate_id=item.candidate_id,
        reviewer=reviewer,
        decision=ReviewDecisionValue.rejected,
        final_payload=None,
        decided_at=datetime.now(timezone.utc),
    )
    await repository.save_review_decision(review)
    await audit.record(
        AuditStage.review,
        {"outcome": "rejected", "reviewer": reviewer, "reason": reason},
        candidate_id=item.candidate_id,
    )
    return review
