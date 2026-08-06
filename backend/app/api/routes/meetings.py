"""Meeting upload + retrieval endpoints."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from app.api import deps
from app.api.schemas import (
    ExtractionDiagnostics,
    MeetingDetailResponse,
    ParticipantIn,
    UploadResponse,
    to_candidate_view,
)
from app.core.config import Settings
from app.domain.models import Participant, TranscriptSegment
from app.domain.safety.gate import check_gate
from app.services.ingestion.parser import TranscriptParseError
from app.services.payload import build_issue_payload
from app.services.pipeline import run_pipeline
from app.services.report import collect_actions_taken, generate_report, render_markdown

logger = logging.getLogger("nexvi_meets.api")

router = APIRouter(prefix="/meetings", tags=["meetings"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # a 45-minute transcript is ~100KB; 5MB is generous


def _parse_participants(raw: str | None) -> list[ParticipantIn]:
    """Accepts a JSON array, or newline-separated "Name <email>" lines.

    The plain-text form exists because typing JSON into a demo form is
    hostile; the JSON form exists because the frontend and the eval
    harness both need structure.
    """
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    if text.startswith("["):
        try:
            return [ParticipantIn.model_validate(p) for p in json.loads(text)]
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(400, f"participants is not valid JSON: {exc}")

    parsed: list[ParticipantIn] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        email = None
        name = line
        if "<" in line and line.endswith(">"):
            name, _, email_part = line.partition("<")
            name = name.strip()
            email = email_part.rstrip(">").strip() or None
        if name:
            parsed.append(ParticipantIn(name=name, email=email))
    return parsed


def _to_domain_participants(items: list[ParticipantIn]) -> list[Participant]:
    domain: list[Participant] = []
    for index, p in enumerate(items):
        pid = p.participant_id or f"p-{p.name.strip().lower().replace(' ', '-')}-{index}"
        domain.append(
            Participant(participant_id=pid, name=p.name, aliases=p.aliases, email=p.email)
        )
    return domain


@router.post("", response_model=UploadResponse)
async def upload_meeting(
    file: UploadFile = File(...),
    title: str = Form(...),
    meeting_date: str = Form(...),
    participants: str | None = Form(None),
    repository=Depends(deps.get_repository),
    settings: Settings = Depends(deps.get_app_settings),
) -> UploadResponse:
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Transcript exceeds the 5MB limit")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Transcript must be UTF-8 text (.txt, .vtt or .srt)")

    try:
        parsed_date = date.fromisoformat(meeting_date)
    except ValueError:
        raise HTTPException(400, "meeting_date must be ISO format, e.g. 2026-08-05")

    participant_models = _to_domain_participants(_parse_participants(participants))
    if not participant_models:
        raise HTTPException(
            400,
            "At least one participant is required. Owner resolution fails closed "
            "without a participant directory, so every item would be blocked.",
        )

    try:
        outcome = await run_pipeline(
            repository=repository,
            filename=file.filename or "transcript.txt",
            content=content,
            title=title,
            meeting_date=parsed_date,
            participants=participant_models,
            settings=settings,
        )
    except TranscriptParseError as exc:
        raise HTTPException(422, f"Could not parse transcript: {exc}")

    # Agents capture failures into the run state rather than raising, so a
    # partial run still produces an honest trace. The API still has to
    # report it as a failure -- "graceful failure" means saying what broke.
    if outcome.error:
        raise HTTPException(422, f"Could not process transcript: {outcome.error}")

    return UploadResponse(
        meeting_id=outcome.meeting_id,
        title=title,
        segments=outcome.segments_count,
        candidates=len(outcome.items),
        eligible=outcome.eligible_count,
        extractor_used=outcome.extractor_used,
        fallback_reason=outcome.fallback_reason,
        warnings=outcome.warnings,
    )


@router.get("", response_model=list[dict])
async def list_meetings(repository=Depends(deps.get_repository)) -> list[dict]:
    """Meeting history, newest first, with the counts a list view needs.

    Aggregated server-side: a client that fetched each meeting's detail to
    render a list of fifty would make fifty round trips.
    """
    return await repository.meeting_summaries()


@router.get("/{meeting_id}/report")
async def meeting_report(
    meeting_id: str,
    repository=Depends(deps.get_repository),
    settings: Settings = Depends(deps.get_app_settings),
) -> dict:
    """The end-to-end report for one meeting.

    Regenerated on every request rather than served from a stored copy,
    so a report opened a week later reflects approvals made since the
    meeting ended instead of freezing at the moment the call dropped.
    """
    stored = await repository.list_segments(meeting_id)
    segments = [TranscriptSegment.model_validate(s) for s in stored] if stored else []

    report = await generate_report(
        repository=repository,
        meeting_id=meeting_id,
        confidence_threshold=settings.confidence_threshold,
        source="live" if any(s.get("track") for s in stored) else "upload",
        segments=segments,
    )
    if report is None:
        raise HTTPException(404, "Meeting not found")
    return report.model_dump(mode="json")


@router.get("/{meeting_id}/report.md", response_class=PlainTextResponse)
async def meeting_report_markdown(
    meeting_id: str,
    repository=Depends(deps.get_repository),
    settings: Settings = Depends(deps.get_app_settings),
) -> str:
    """The same report as shareable markdown, for pasting into Slack."""
    stored = await repository.list_segments(meeting_id)
    segments = [TranscriptSegment.model_validate(s) for s in stored] if stored else []
    report = await generate_report(
        repository=repository,
        meeting_id=meeting_id,
        confidence_threshold=settings.confidence_threshold,
        source="live" if any(s.get("track") for s in stored) else "upload",
        segments=segments,
    )
    if report is None:
        raise HTTPException(404, "Meeting not found")
    return render_markdown(report)


@router.get("/{meeting_id}/actions")
async def meeting_actions(meeting_id: str, repository=Depends(deps.get_repository)) -> dict:
    """Every external action taken for this meeting, successes and failures.

    Read from the side-effect ledgers rather than the audit narrative, so
    "was an issue actually created" has one honest answer.
    """
    if not await repository.get_meeting(meeting_id):
        raise HTTPException(404, "Meeting not found")
    actions = await collect_actions_taken(repository, meeting_id)
    return {
        "meeting_id": meeting_id,
        "count": len(actions),
        "actions": [a.model_dump(mode="json") for a in actions],
    }


@router.get("/{meeting_id}/transcript")
async def meeting_transcript(meeting_id: str, repository=Depends(deps.get_repository)) -> dict:
    if not await repository.get_meeting(meeting_id):
        raise HTTPException(404, "Meeting not found")
    segments = await repository.list_segments(meeting_id)
    return {"meeting_id": meeting_id, "segment_count": len(segments), "segments": segments}


@router.delete("/{meeting_id}", status_code=200)
async def delete_meeting(
    meeting_id: str,
    repository=Depends(deps.get_repository),
) -> dict:
    """Hard-delete all data for one meeting.

    Removes the meeting and every related document (items, review decisions,
    audit events, issue records, calendar events, notifications, agent run,
    transcript segments). The GitHub issue that was already created on the
    remote tracker is NOT deleted — it is an external side effect that has
    left this system, and the audit principle requires that remote artefacts
    are not silently wiped.

    An audit event is written *before* deletion so that even after the
    meeting is gone, the Atlas audit oplog retains a tombstone of when and
    what was deleted.
    """
    from datetime import datetime, timezone
    from app.domain.models import AuditStage
    from app.services.audit import AuditLogger

    meeting = await repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    # Write tombstone audit event first
    audit = AuditLogger(repository, meeting_id)
    await audit.record(
        AuditStage.review,
        {
            "outcome": "meeting_deleted",
            "title": meeting.get("title", ""),
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "note": "All local data deleted. Remote GitHub issues are NOT deleted.",
        },
    )

    db = repository._db
    deleted = {}
    for coll, field in [
        ("nm_meetings", "meeting_id"),
        ("nm_meeting_records", "meeting_id"),
        ("nm_items", "meeting_id"),
        ("nm_review", None),          # keyed by candidate_id, handled below
        ("nm_audit", "meeting_id"),
        ("nm_issues", "meeting_id"),
        ("nm_calendar", "meeting_id"),
        ("nm_notifications", "meeting_id"),
        ("nm_agent_runs", "meeting_id"),
        ("nm_segments", "meeting_id"),
    ]:
        if field == "meeting_id":
            result = await db[coll].delete_many({"meeting_id": meeting_id})
        elif coll == "nm_review":
            # Review decisions are keyed by candidate_id — collect them first
            candidate_ids = [
                d["candidate_id"]
                async for d in db.nm_items.find({"meeting_id": meeting_id}, {"candidate_id": 1})
            ]
            if candidate_ids:
                result = await db.nm_review.delete_many(
                    {"candidate_id": {"$in": candidate_ids}}
                )
            else:
                result = type("R", (), {"deleted_count": 0})()
        else:
            result = type("R", (), {"deleted_count": 0})()
        deleted[coll] = result.deleted_count

    return {
        "meeting_id": meeting_id,
        "title": meeting.get("title", ""),
        "deleted": deleted,
        "message": "Meeting and all local data deleted. Remote GitHub issues are preserved.",
    }


@router.get("/{meeting_id}", response_model=MeetingDetailResponse)
async def get_meeting(
    meeting_id: str,
    repository=Depends(deps.get_repository),
    settings: Settings = Depends(deps.get_app_settings),
) -> MeetingDetailResponse:
    meeting = await repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    participants = [Participant.model_validate(p) for p in meeting.get("participants", [])]
    name_by_id = {p.participant_id: p.name for p in participants}
    items = await repository.list_items(meeting_id)
    record = await repository.get_meeting_record(meeting_id)

    views = []
    for item in items:
        gate = check_gate(item, settings.confidence_threshold)
        decision = await repository.get_review_decision(item.candidate_id)
        issue = None
        if decision and decision.decision.value != "rejected":
            records = await repository.list_issue_records(meeting_id)
            issue = next((r for r in records if r.candidate_id == item.candidate_id), None)
        payload = (
            build_issue_payload(item, participants, meeting.get("title", ""))
            if gate.eligible
            else None
        )
        views.append(
            to_candidate_view(
                item,
                gate,
                name_by_id.get(item.owner_participant_id or ""),
                payload,
                decision.decision.value if decision else None,
                issue.github_issue_url if issue else None,
            )
        )

    return MeetingDetailResponse(
        meeting_id=meeting_id,
        title=meeting.get("title", ""),
        meeting_date=meeting.get("meeting_date", ""),
        participants=meeting.get("participants", []),
        record=record,
        candidates=views,
        extraction=await _extraction_diagnostics(repository, meeting_id, len(views)),
    )


async def _extraction_diagnostics(
    repository, meeting_id: str, candidate_count: int
) -> ExtractionDiagnostics:
    """Reconstruct what extraction did, from the audit log.

    The audit log is already the system's record of every stage, so
    reading it here avoids storing the same facts twice and works
    identically for uploads (which run the agent graph) and live meetings
    (which do not).
    """
    diagnostics = ExtractionDiagnostics(candidates_found=candidate_count)
    try:
        events = await repository.list_audit(meeting_id)
    except Exception as exc:  # noqa: BLE001 -- must never break the page...
        # ...but must not vanish either. A silent except here is how the
        # original bug hid: swallow the error, return nothing, look fine.
        logger.warning("could not read audit log for %s: %s", meeting_id, exc)
        diagnostics.warnings.append(f"Diagnostics unavailable: {exc}")
        return diagnostics

    for event in events:
        payload = event.payload if hasattr(event, "payload") else event.get("payload", {})
        if not isinstance(payload, dict):
            continue

        if payload.get("extractor"):
            diagnostics.extractor = payload["extractor"]
        if payload.get("fallback_reason"):
            diagnostics.fallback_reason = payload["fallback_reason"]
        if payload.get("extraction_error"):
            diagnostics.fallback_reason = payload["extraction_error"]
        if payload.get("segments"):
            diagnostics.segments = max(diagnostics.segments, int(payload["segments"]))
        if payload.get("evidence_dropped_items"):
            diagnostics.evidence_dropped_items = int(payload["evidence_dropped_items"])
        if payload.get("evidence_quotes_dropped"):
            diagnostics.evidence_quotes_dropped = int(payload["evidence_quotes_dropped"])
        for warning in payload.get("warnings") or []:
            if warning not in diagnostics.warnings:
                diagnostics.warnings.append(warning)

    return diagnostics
