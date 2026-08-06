"""F012: the human-in-the-loop review API.

Approve is the only endpoint in the application that can cause an
external side effect, and it delegates the decision to
``app/services/approval.py`` rather than deciding anything itself. The
route's job is HTTP: load, validate input, translate a refusal into a
422 with the gate's reasons attached.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api import deps
from app.api.schemas import (
    ApproveRequest,
    ApproveResponse,
    AuditEventView,
    EditRequest,
    RejectRequest,
)
from app.core.config import Settings
from app.domain.models import AuditStage, Participant, SideEffect
from app.services.approval import ApprovalRefused, approve_and_execute, reject_candidate
from app.services.audit import AuditLogger
from app.services.payload import build_issue_payload

router = APIRouter(prefix="/review", tags=["review"])


async def _load(repository, candidate_id: str):
    item = await repository.get_item(candidate_id)
    if not item:
        raise HTTPException(404, "Candidate not found")
    meeting = await repository.get_meeting(item.meeting_id)
    participants = [Participant.model_validate(p) for p in (meeting or {}).get("participants", [])]
    return item, meeting or {}, participants


def _requested_effects(names: list[str] | None) -> tuple[SideEffect, ...]:
    """Which side effects this approval should fire.

    Defaults to GitHub only. A reviewer opting into calendar/memory/
    notification is an explicit, per-approval choice -- approving a
    commitment must never quietly fan out to more external systems than
    the person expected.
    """
    if not names:
        return (SideEffect.github_issue,)
    try:
        return tuple(SideEffect(n) for n in names)
    except ValueError as exc:
        raise HTTPException(
            400,
            f"Unknown side effect requested. Valid: {[e.value for e in SideEffect]} ({exc})",
        )


@router.post("/candidates/{candidate_id}/approve", response_model=ApproveResponse)
async def approve(
    candidate_id: str,
    body: ApproveRequest,
    repository=Depends(deps.get_repository),
    tracker=Depends(deps.get_tracker),
    calendar=Depends(deps.get_calendar),
    memory_store=Depends(deps.get_memory_store),
    registry=Depends(deps.get_tool_registry),
    settings: Settings = Depends(deps.get_app_settings),
) -> ApproveResponse:
    item, meeting, participants = await _load(repository, candidate_id)

    # The reviewer may hand back an edited payload; otherwise we rebuild
    # it from the stored item so the approved payload always matches the
    # item the gate just evaluated.
    payload = body.payload or build_issue_payload(item, participants, meeting.get("title", ""))

    try:
        result = await approve_and_execute(
            repository=repository,
            registry=registry,
            item=item,
            payload=payload,
            reviewer=body.reviewer,
            confidence_threshold=settings.confidence_threshold,
            edited=body.payload is not None,
            participants=participants,
            meeting_title=meeting.get("title", ""),
            meeting_date=meeting.get("meeting_date", ""),
            effects=_requested_effects(body.effects),
            tracker=tracker,
            calendar=calendar,
            memory_store=memory_store,
        )
    except ApprovalRefused as exc:
        raise HTTPException(422, detail={"message": str(exc), "reasons": exc.reasons})

    return ApproveResponse(
        candidate_id=candidate_id,
        created=result.created,
        duplicate_suppressed=result.duplicate_suppressed,
        issue_number=result.issue_number,
        issue_url=result.issue_url,
        dedupe_key=result.dedupe_key,
        effects=[
            {"effect": e.effect, "status": e.status, "detail": e.detail, "error": e.error}
            for e in result.effects
        ],
    )


@router.post("/candidates/{candidate_id}/reject")
async def reject(
    candidate_id: str,
    body: RejectRequest,
    repository=Depends(deps.get_repository),
) -> dict:
    item, _, _ = await _load(repository, candidate_id)
    await reject_candidate(
        repository=repository, item=item, reviewer=body.reviewer, reason=body.reason
    )
    return {"candidate_id": candidate_id, "status": "rejected"}


@router.patch("/candidates/{candidate_id}")
async def edit(
    candidate_id: str,
    body: EditRequest,
    repository=Depends(deps.get_repository),
) -> dict:
    """Edit the candidate itself, not the payload.

    Editing the item means the safety gate re-evaluates the *edited*
    values on the next approve call -- a reviewer fixing an owner makes
    the item legitimately eligible, rather than letting them paste a
    hand-written payload past a gate that never saw it.
    """
    item, meeting, participants = await _load(repository, candidate_id)

    changes = body.model_dump(exclude={"reviewer"}, exclude_none=True)
    if not changes:
        raise HTTPException(400, "No fields to update")

    valid_ids = {p.participant_id for p in participants}
    if "owner_participant_id" in changes and changes["owner_participant_id"] not in valid_ids:
        raise HTTPException(
            400,
            f"owner_participant_id must be one of this meeting's participants: {sorted(valid_ids)}",
        )

    update: dict = dict(changes)
    if "owner_participant_id" in update:
        # A human picking the owner is a stronger signal than any
        # matcher, so the resolution method records that provenance.
        from app.domain.models import OwnerResolutionMethod

        update["owner_resolution_method"] = OwnerResolutionMethod.exact_match
    if "due_date" in update:
        from app.domain.models import DateResolutionMethod

        update["date_resolution_method"] = DateResolutionMethod.absolute

    # Recompute the composite confidence: a reviewer who just fixed an
    # unresolvable owner must not stay blocked by a score that was low
    # *because* the owner was unresolvable.
    from app.services.resolvers.combine import recompute_confidence

    edited_item = recompute_confidence(item.model_copy(update=update))
    await repository.update_item(edited_item)

    audit = AuditLogger(repository, item.meeting_id)
    await audit.record(
        AuditStage.review,
        {
            "outcome": "edited",
            "reviewer": body.reviewer,
            "changed_fields": {
                k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in changes.items()
            },
            "edited_at": datetime.now(timezone.utc).isoformat(),
        },
        candidate_id=candidate_id,
    )

    return {
        "candidate_id": candidate_id,
        "status": "edited",
        "changed_fields": sorted(changes.keys()),
    }


@router.get("/meetings/{meeting_id}/audit", response_model=list[AuditEventView])
async def audit_log(meeting_id: str, repository=Depends(deps.get_repository)):
    events = await repository.list_audit(meeting_id)
    return [AuditEventView.model_validate(e.model_dump()) for e in events]
