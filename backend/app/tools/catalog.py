"""The tool catalogue.

Every capability an agent can use, declared with metadata. Business logic
lives in ``app/services`` and ``app/adapters``; these wrappers only make
it addressable by name and mark which ones touch the outside world.

Four tools are side-effecting. Those four are the entire external surface
of Nexvi.Meets, and none of them can be invoked through the registry
without a passing gate decision plus a human approval:

    github_issue     create a GitHub issue
    calendar_invite  create a per-owner Calendar event
    memory_index     index an approved commitment for cross-meeting recall
    notification     record that an owner was notified

Everything else is pure computation or a read.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.adapters.calendar.base import CalendarInvite
from app.adapters.trackers.base import IssuePayload
from app.domain.models import (
    MemoryRecord,
    NotificationRecord,
    Participant,
    ResolvedItem,
    TranscriptSegment,
)
from app.domain.safety.gate import check_gate
from app.services.confidence import compute_confidence
from app.services.extraction.base import drop_unsupported_evidence
from app.services.idempotency import compute_dedupe_key
from app.services.ingestion.normalization import normalize
from app.services.ingestion.parser import parse_transcript
from app.services.meeting_record import synthesize_meeting_record
from app.services.resolvers.combine import resolve_validated_items
from app.services.resolvers.date import resolve_date
from app.services.resolvers.owner import resolve_owner
from app.tools.base import FunctionTool, ToolSpec
from app.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


async def _parse_transcript(*, filename: str, content: str) -> list:
    return parse_transcript(filename, content)


async def _normalize_segments(*, utterances: list, meeting_id: str) -> list[TranscriptSegment]:
    return normalize(utterances, meeting_id=meeting_id)


async def _translate_segments(*, segments: list[TranscriptSegment], normalizer) -> list:
    return await normalizer.normalize(segments)


async def _extract(*, extractor, segments: list[TranscriptSegment], meeting_id: str) -> list:
    return extractor.extract(segments, meeting_id)


async def _grade_evidence(*, items: list, segments: list[TranscriptSegment], report=None) -> list:
    # `report` is an out-parameter so the caller can explain *why* items
    # disappeared. Optional, so every existing call site still works.
    return drop_unsupported_evidence(items, segments, report)


async def _resolve_owner(*, mention: Optional[str], participants: list[Participant]):
    return resolve_owner(mention, participants)


async def _resolve_date(*, mention: Optional[str], meeting_date: date):
    return resolve_date(mention, meeting_date)


async def _resolve_all(*, items: list, participants: list[Participant], meeting_date: date):
    return resolve_validated_items(items, participants, meeting_date)


async def _score_confidence(**kwargs: Any) -> float:
    return compute_confidence(**kwargs)


async def _run_gate(*, item: ResolvedItem, confidence_threshold: float):
    return check_gate(item, confidence_threshold)


async def _synthesize_record(*, meeting_id: str, items: list):
    return synthesize_meeting_record(meeting_id, items)


async def _dedupe_key(*, meeting_id: str, owner_participant_id: Optional[str], text: str) -> str:
    return compute_dedupe_key(meeting_id, owner_participant_id, text)


async def _recall_memory(*, store, query: str, limit: int = 5, exclude_meeting_id: str | None = None):
    return await store.search(query, limit=limit, exclude_meeting_id=exclude_meeting_id)


# ---------------------------------------------------------------------------
# Side-effecting tools
# ---------------------------------------------------------------------------


async def _create_github_issue(*, tracker, payload: IssuePayload):
    return await tracker.create_issue(payload)


async def _create_calendar_invite(*, calendar, invite: CalendarInvite):
    return await calendar.create_invite(invite)


async def _index_memory(
    *,
    store,
    item: ResolvedItem,
    meeting_title: str,
    meeting_date: str,
) -> MemoryRecord:
    record = MemoryRecord(
        memory_id=f"{item.meeting_id}:{item.candidate_id}",
        candidate_id=item.candidate_id,
        meeting_id=item.meeting_id,
        meeting_title=meeting_title,
        meeting_date=meeting_date,
        text=item.raw_text,
        owner_participant_id=item.owner_participant_id,
        due_date=item.due_date,
        created_at=datetime.now(timezone.utc),
    )
    await store.index(record)
    return record


async def _record_notification(
    *,
    repository,
    item: ResolvedItem,
    owner_email: str,
    channel: str = "calendar",
) -> NotificationRecord:
    """Bookkeeping for "this owner was told".

    Honest scope note, carried over from the archived implementation: no
    background scheduler exists, so ``reminder_at`` is a computed
    *intent*, not a job that will fire. The Calendar invite is what
    actually reaches the owner today.
    """
    reminder_at = None
    if item.due_date:
        due = datetime.combine(item.due_date, datetime.min.time(), tzinfo=timezone.utc)
        candidate_time = due - timedelta(hours=24)
        now = datetime.now(timezone.utc)
        reminder_at = candidate_time if candidate_time > now else now

    record = NotificationRecord(
        notification_id=str(uuid.uuid4()),
        candidate_id=item.candidate_id,
        meeting_id=item.meeting_id,
        owner_email=owner_email,
        channel=channel,
        reminder_at=reminder_at,
        created_at=datetime.now(timezone.utc),
    )
    await repository.save_notification(record)
    return record


# ---------------------------------------------------------------------------
# Registry construction
# ---------------------------------------------------------------------------

_READ_ONLY: list[tuple[ToolSpec, Any]] = [
    (ToolSpec("parse_transcript", "Parse a .txt/.vtt/.srt file into raw utterances.", tags=("ingestion",)), _parse_transcript),
    (ToolSpec("normalize_segments", "Assign stable segment ids to utterances.", tags=("ingestion",)), _normalize_segments),
    (ToolSpec("translate_segments", "Add an English rendering of code-switched segments, leaving the original verbatim text intact.", system="sarvam", tags=("ingestion", "code-switch")), _translate_segments),
    (ToolSpec("extract_candidates", "Extract and classify commitment candidates from transcript segments.", system="groq", tags=("extraction",)), _extract),
    (ToolSpec("grade_evidence", "Delete any evidence quote that is not a verbatim substring of the segment it cites.", tags=("extraction", "safety")), _grade_evidence),
    (ToolSpec("resolve_owner", "Resolve a spoken name to exactly one participant, or to nothing.", tags=("resolution",)), _resolve_owner),
    (ToolSpec("resolve_date", "Resolve a spoken date phrase against the meeting date.", tags=("resolution",)), _resolve_date),
    (ToolSpec("resolve_items", "Resolve owner and date for every candidate and compute composite confidence.", tags=("resolution",)), _resolve_all),
    (ToolSpec("score_confidence", "Blend extraction confidence with owner/date resolution outcomes.", tags=("resolution",)), _score_confidence),
    (ToolSpec("safety_gate", "Evaluate the six deterministic rules for one resolved item.", tags=("safety",)), _run_gate),
    (ToolSpec("synthesize_record", "Build the structured meeting record.", tags=("record",)), _synthesize_record),
    (ToolSpec("compute_dedupe_key", "Compute the idempotency key for a commitment.", tags=("idempotency",)), _dedupe_key),
    (ToolSpec("recall_memory", "Search previously approved commitments across meetings.", system="chroma", tags=("memory",)), _recall_memory),
]

_SIDE_EFFECTING: list[tuple[ToolSpec, Any]] = [
    (ToolSpec("github_issue", "Create a GitHub issue for an approved commitment.", side_effecting=True, system="github", tags=("side-effect",)), _create_github_issue),
    (ToolSpec("calendar_invite", "Create a personal calendar event for the owner of an approved commitment.", side_effecting=True, system="google_calendar", tags=("side-effect",)), _create_calendar_invite),
    (ToolSpec("memory_index", "Index an approved commitment for cross-meeting recall.", side_effecting=True, system="chroma", tags=("side-effect", "memory")), _index_memory),
    (ToolSpec("notification", "Record that the owner of an approved commitment was notified.", side_effecting=True, system="internal", tags=("side-effect",)), _record_notification),
]


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for spec, fn in _READ_ONLY + _SIDE_EFFECTING:
        registry.register(FunctionTool(spec, fn))
    return registry
