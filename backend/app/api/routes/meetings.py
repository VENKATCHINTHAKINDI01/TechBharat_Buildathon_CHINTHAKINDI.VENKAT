"""Meeting upload + retrieval endpoints."""
from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api import deps
from app.api.schemas import (
    MeetingDetailResponse,
    ParticipantIn,
    UploadResponse,
    to_candidate_view,
)
from app.core.config import Settings
from app.domain.models import Participant
from app.domain.safety.gate import check_gate
from app.services.ingestion.parser import TranscriptParseError
from app.services.payload import build_issue_payload
from app.services.pipeline import run_pipeline

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
    return await repository.list_meetings()


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
    )
