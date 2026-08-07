"""MongoDB repository (motor). The runtime persistence implementation.

Collections (all prefixed so Nexvi.Meets can share a database without
colliding with anything else):

- ``nm_meetings``        one document per uploaded meeting
- ``nm_meeting_records`` the structured record (F011b), one per meeting
- ``nm_items``           resolved candidate items, keyed by candidate_id
- ``nm_review``          human review decisions, keyed by candidate_id
- ``nm_audit``           append-only audit events
- ``nm_issues``          created issue records, keyed by dedupe_key

``ensure_indexes`` creates a **unique** index on ``nm_issues.dedupe_key``.
That unique constraint -- not application logic alone -- is what makes
duplicate suppression (F015) hold even under concurrent approvals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.domain.models import (
    AgentRun,
    AuditEvent,
    CalendarEventRecord,
    GitHubIssueRecord,
    MeetingRecord,
    NotificationRecord,
    Participant,
    ResolvedItem,
    ReviewDecision,
)

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        uri = get_settings().require_mongo_uri()
        _client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    return _client


def get_database() -> AsyncIOMotorDatabase:
    settings = get_settings()
    return get_client()[settings.mongo_db_name]


def _strip_id(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


class MongoRepository:
    def __init__(self, db: AsyncIOMotorDatabase | None = None) -> None:
        self._db = db if db is not None else get_database()

    async def ensure_indexes(self) -> None:
        await self._db.nm_issues.create_index("dedupe_key", unique=True)
        await self._db.nm_items.create_index("candidate_id", unique=True)
        await self._db.nm_items.create_index("meeting_id")
        await self._db.nm_audit.create_index([("meeting_id", 1), ("created_at", 1)])
        await self._db.nm_review.create_index("candidate_id", unique=True)
        await self._db.nm_meetings.create_index("meeting_id", unique=True)
        await self._db.nm_meeting_records.create_index("meeting_id", unique=True)
        # Same unique-index guarantee as issues: the database, not app
        # logic, is what stops a duplicate calendar invite.
        await self._db.nm_calendar.create_index("dedupe_key", unique=True)
        await self._db.nm_notifications.create_index("meeting_id")
        await self._db.nm_agent_runs.create_index("meeting_id", unique=True)
        await self._db.nm_segments.create_index("meeting_id", unique=True)
        # Newest-first history without a full collection scan.
        await self._db.nm_meetings.create_index("created_at")

    # --- meetings ---
    async def create_meeting(
        self, meeting_id: str, title: str, meeting_date: str, participants: list[Participant]
    ) -> None:
        await self._db.nm_meetings.update_one(
            {"meeting_id": meeting_id},
            {
                "$set": {
                    "meeting_id": meeting_id,
                    "title": title,
                    "meeting_date": meeting_date,
                    "participants": [p.model_dump() for p in participants],
                },
                # Only on insert: re-running a meeting must not reset when
                # it was first seen, or history ordering would shuffle.
                "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()},
            },
            upsert=True,
        )

    async def update_participants(
        self, meeting_id: str, participants: list[Participant]
    ) -> None:
        """Replace the roster of a meeting already in progress."""
        await self._db.nm_meetings.update_one(
            {"meeting_id": meeting_id},
            {"$set": {"participants": [p.model_dump() for p in participants]}},
        )

    async def get_meeting(self, meeting_id: str) -> Optional[dict]:
        return _strip_id(await self._db.nm_meetings.find_one({"meeting_id": meeting_id}))

    async def list_meetings(self) -> list[dict]:
        return [_strip_id(d) async for d in self._db.nm_meetings.find()]

    # --- meeting record ---
    async def save_meeting_record(self, record: MeetingRecord) -> None:
        await self._db.nm_meeting_records.update_one(
            {"meeting_id": record.meeting_id},
            {"$set": record.model_dump(mode="json")},
            upsert=True,
        )

    async def get_meeting_record(self, meeting_id: str) -> Optional[MeetingRecord]:
        doc = _strip_id(await self._db.nm_meeting_records.find_one({"meeting_id": meeting_id}))
        return MeetingRecord.model_validate(doc) if doc else None

    # --- items ---
    async def save_items(self, items: list[ResolvedItem]) -> None:
        for item in items:
            await self.update_item(item)

    async def delete_items(self, meeting_id: str) -> int:
        """Remove a meeting's candidates so re-analysis starts clean."""
        result = await self._db.nm_items.delete_many({"meeting_id": meeting_id})
        return result.deleted_count

    async def list_items(self, meeting_id: str) -> list[ResolvedItem]:
        return [
            ResolvedItem.model_validate(_strip_id(d))
            async for d in self._db.nm_items.find({"meeting_id": meeting_id}).sort("candidate_id", 1)
        ]

    async def get_item(self, candidate_id: str) -> Optional[ResolvedItem]:
        doc = _strip_id(await self._db.nm_items.find_one({"candidate_id": candidate_id}))
        return ResolvedItem.model_validate(doc) if doc else None

    async def update_item(self, item: ResolvedItem) -> None:
        await self._db.nm_items.update_one(
            {"candidate_id": item.candidate_id},
            {"$set": item.model_dump(mode="json")},
            upsert=True,
        )

    # --- review ---
    async def save_review_decision(self, decision: ReviewDecision) -> None:
        await self._db.nm_review.update_one(
            {"candidate_id": decision.candidate_id},
            {"$set": decision.model_dump(mode="json")},
            upsert=True,
        )

    async def get_review_decision(self, candidate_id: str) -> Optional[ReviewDecision]:
        doc = _strip_id(await self._db.nm_review.find_one({"candidate_id": candidate_id}))
        return ReviewDecision.model_validate(doc) if doc else None

    # --- audit (append-only: insert, never update) ---
    async def append_audit(self, event: AuditEvent) -> None:
        await self._db.nm_audit.insert_one(event.model_dump(mode="json"))

    async def list_audit(self, meeting_id: str) -> list[AuditEvent]:
        return [
            AuditEvent.model_validate(_strip_id(d))
            async for d in self._db.nm_audit.find({"meeting_id": meeting_id}).sort("created_at", 1)
        ]

    # --- issue records ---
    async def save_issue_record(self, record: GitHubIssueRecord) -> None:
        try:
            await self._db.nm_issues.insert_one(record.model_dump(mode="json"))
        except DuplicateKeyError:
            # Another approval already created an issue for this dedupe_key.
            # Swallowing this is correct and is the point of the unique
            # index: the first write wins, the second is a no-op.
            pass

    async def find_issue_by_dedupe_key(self, dedupe_key: str) -> Optional[GitHubIssueRecord]:
        doc = _strip_id(await self._db.nm_issues.find_one({"dedupe_key": dedupe_key}))
        return GitHubIssueRecord.model_validate(doc) if doc else None

    async def list_issue_records(self, meeting_id: str) -> list[GitHubIssueRecord]:
        return [
            GitHubIssueRecord.model_validate(_strip_id(d))
            async for d in self._db.nm_issues.find({"meeting_id": meeting_id})
        ]

    # --- calendar events ---
    async def save_calendar_event(self, record: CalendarEventRecord) -> None:
        try:
            await self._db.nm_calendar.insert_one(record.model_dump(mode="json"))
        except DuplicateKeyError:
            pass  # first write wins; see save_issue_record

    async def find_calendar_event_by_dedupe_key(
        self, dedupe_key: str
    ) -> Optional[CalendarEventRecord]:
        doc = _strip_id(await self._db.nm_calendar.find_one({"dedupe_key": dedupe_key}))
        return CalendarEventRecord.model_validate(doc) if doc else None

    async def list_calendar_events(self, meeting_id: str) -> list[CalendarEventRecord]:
        return [
            CalendarEventRecord.model_validate(_strip_id(d))
            async for d in self._db.nm_calendar.find({"meeting_id": meeting_id})
        ]

    # --- notifications ---
    async def save_notification(self, record: NotificationRecord) -> None:
        await self._db.nm_notifications.insert_one(record.model_dump(mode="json"))

    async def list_notifications(self, meeting_id: str) -> list[NotificationRecord]:
        return [
            NotificationRecord.model_validate(_strip_id(d))
            async for d in self._db.nm_notifications.find({"meeting_id": meeting_id})
        ]

    # --- agent runs ---
    async def save_agent_run(self, run: AgentRun) -> None:
        await self._db.nm_agent_runs.update_one(
            {"meeting_id": run.meeting_id},
            {"$set": run.model_dump(mode="json")},
            upsert=True,
        )

    async def get_agent_run(self, meeting_id: str) -> Optional[AgentRun]:
        doc = _strip_id(await self._db.nm_agent_runs.find_one({"meeting_id": meeting_id}))
        return AgentRun.model_validate(doc) if doc else None

    # --- transcript ---
    async def save_segments(self, meeting_id: str, segments: list[dict]) -> None:
        await self._db.nm_segments.update_one(
            {"meeting_id": meeting_id},
            {"$set": {"meeting_id": meeting_id, "segments": segments}},
            upsert=True,
        )

    async def list_segments(self, meeting_id: str) -> list[dict]:
        doc = _strip_id(await self._db.nm_segments.find_one({"meeting_id": meeting_id}))
        return (doc or {}).get("segments", [])

    # --- history ---
    async def meeting_summaries(self) -> list[dict]:
        """One row per meeting with the counts the history view needs.

        Aggregated per meeting rather than joined in the client: a list of
        50 meetings would otherwise be 50 round trips.
        """
        out = []
        async for meeting in self._db.nm_meetings.find().sort("created_at", -1):
            mid = meeting["meeting_id"]
            reviewed = 0
            candidate_ids = [
                d["candidate_id"]
                async for d in self._db.nm_items.find({"meeting_id": mid}, {"candidate_id": 1})
            ]
            if candidate_ids:
                reviewed = await self._db.nm_review.count_documents(
                    {"candidate_id": {"$in": candidate_ids}}
                )
            segments_doc = await self._db.nm_segments.find_one({"meeting_id": mid})
            out.append(
                {
                    **(_strip_id(meeting) or {}),
                    "action_items": await self._db.nm_items.count_documents(
                        {"meeting_id": mid, "kind": "action_item"}
                    ),
                    "candidates": len(candidate_ids),
                    "reviewed": reviewed,
                    "issues_created": await self._db.nm_issues.count_documents({"meeting_id": mid}),
                    "calendar_events": await self._db.nm_calendar.count_documents(
                        {"meeting_id": mid}
                    ),
                    "segments": len((segments_doc or {}).get("segments", [])),
                    "has_record": bool(
                        await self._db.nm_meeting_records.find_one({"meeting_id": mid})
                    ),
                }
            )
        return out
