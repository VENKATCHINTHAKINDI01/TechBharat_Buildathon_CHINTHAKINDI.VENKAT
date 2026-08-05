"""The approval service -- the single chokepoint for external side effects.

Everything the brief scores as a hard requirement converges here:

- "Nothing is created, sent or posted until a person sees the exact
  payload and approves it"  -> an explicit ReviewDecision is required.
- "Zero unapproved actions"                                  -> the gate
  is re-evaluated server-side at approval time, not trusted from the UI.
- "Running the same meeting twice must not create duplicate tasks"
                                                             -> dedupe
  key checked before the call, issue record written after it.
- "An audit log showing every action the agent took, what it was based
  on, and who approved it"      -> every branch below writes an event,
  including the refusals.

Deliberate design choice: the gate is re-run here against freshly
persisted data even though the review API already checked it. A client
can call any endpoint in any order; the invariant must hold at the point
of the side effect, not at the point of the UI's last render.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.adapters.trackers.base import IssuePayload, IssueTracker, IssueTrackerError
from app.domain.models import (
    AuditStage,
    GitHubIssueRecord,
    Participant,
    ResolvedItem,
    ReviewDecision,
    ReviewDecisionValue,
)
from app.domain.safety.gate import check_gate
from app.services.audit import AuditLogger
from app.services.idempotency import compute_dedupe_key


class ApprovalRefused(RuntimeError):
    """Raised when an approval cannot proceed. Carries the gate reasons so
    the API can show the reviewer exactly which rule blocked it."""

    def __init__(self, message: str, reasons: list[str] | None = None) -> None:
        super().__init__(message)
        self.reasons = reasons or []


class ApprovalResult:
    def __init__(
        self,
        created: bool,
        issue_number: int | None,
        issue_url: str | None,
        duplicate_suppressed: bool,
        dedupe_key: str,
    ) -> None:
        self.created = created
        self.issue_number = issue_number
        self.issue_url = issue_url
        self.duplicate_suppressed = duplicate_suppressed
        self.dedupe_key = dedupe_key

    def as_dict(self) -> dict:
        return {
            "created": self.created,
            "issue_number": self.issue_number,
            "issue_url": self.issue_url,
            "duplicate_suppressed": self.duplicate_suppressed,
            "dedupe_key": self.dedupe_key,
        }


async def approve_and_create_issue(
    *,
    repository,
    tracker: IssueTracker,
    item: ResolvedItem,
    payload: IssuePayload,
    reviewer: str,
    confidence_threshold: float,
    edited: bool,
    participants: list[Participant],
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
            {
                "outcome": "approval_refused",
                "reviewer": reviewer,
                "reasons": decision.reasons,
            },
            candidate_id=item.candidate_id,
        )
        raise ApprovalRefused(
            "Candidate is not eligible for issue creation.", decision.reasons
        )

    # --- 2. Record the human decision *before* the side effect, so an
    #        approval is never missing from the trail if the call fails. ---
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
        },
        candidate_id=item.candidate_id,
    )

    # --- 3. Idempotency check before any network call. ---
    dedupe_key = compute_dedupe_key(
        item.meeting_id, item.owner_participant_id, payload.title
    )
    existing = await repository.find_issue_by_dedupe_key(dedupe_key)
    if existing is not None:
        await audit.record(
            AuditStage.dedupe,
            {
                "outcome": "duplicate_suppressed",
                "dedupe_key": dedupe_key,
                "existing_issue_number": existing.github_issue_number,
                "existing_issue_url": existing.github_issue_url,
            },
            candidate_id=item.candidate_id,
        )
        return ApprovalResult(
            created=False,
            issue_number=existing.github_issue_number,
            issue_url=existing.github_issue_url,
            duplicate_suppressed=True,
            dedupe_key=dedupe_key,
        )

    # --- 4. The side effect. ---
    try:
        created = await tracker.create_issue(payload)
    except IssueTrackerError as exc:
        await audit.record(
            AuditStage.github_create,
            {"outcome": "failed", "error": str(exc), "payload": payload.model_dump()},
            candidate_id=item.candidate_id,
        )
        raise

    record = GitHubIssueRecord(
        dedupe_key=dedupe_key,
        candidate_id=item.candidate_id,
        meeting_id=item.meeting_id,
        github_issue_number=created.number,
        github_issue_url=created.url,
        created_at=datetime.now(timezone.utc),
    )
    await repository.save_issue_record(record)
    await audit.record(
        AuditStage.github_create,
        {
            "outcome": "created",
            "tracker": getattr(tracker, "name", "unknown"),
            "issue_number": created.number,
            "issue_url": created.url,
            "dedupe_key": dedupe_key,
            "payload": payload.model_dump(),
            "approved_by": reviewer,
        },
        candidate_id=item.candidate_id,
    )

    return ApprovalResult(
        created=True,
        issue_number=created.number,
        issue_url=created.url,
        duplicate_suppressed=False,
        dedupe_key=dedupe_key,
    )


async def reject_candidate(
    *, repository, item: ResolvedItem, reviewer: str, reason: str | None
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
