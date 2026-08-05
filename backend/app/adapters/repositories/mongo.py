"""MongoDB repository (motor). The runtime persistence implementation.

Collections (all prefixed so CommitGuard can share a database without
colliding with anything else):

- ``cg_meetings``        one document per uploaded meeting
- ``cg_meeting_records`` the structured record (F011b), one per meeting
- ``cg_items``           resolved candidate items, keyed by candidate_id
- ``cg_review``          human review decisions, keyed by candidate_id
- ``cg_audit``           append-only audit events
- ``cg_issues``          created issue records, keyed by dedupe_key

``ensure_indexes`` creates a **unique** index on ``cg_issues.dedupe_key``.
That unique constraint -- not application logic alone -- is what makes
duplicate suppression (F015) hold even under concurrent approvals.
"""
from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.domain.models import (
    AuditEvent,
    GitHubIssueRecord,
    MeetingRecord,
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
        await self._db.cg_issues.create_index("dedupe_key", unique=True)
        await self._db.cg_items.create_index("candidate_id", unique=True)
        await self._db.cg_items.create_index("meeting_id")
        await self._db.cg_audit.create_index([("meeting_id", 1), ("created_at", 1)])
        await self._db.cg_review.create_index("candidate_id", unique=True)
        await self._db.cg_meetings.create_index("meeting_id", unique=True)
        await self._db.cg_meeting_records.create_index("meeting_id", unique=True)

    # --- meetings ---
    async def create_meeting(
        self, meeting_id: str, title: str, meeting_date: str, participants: list[Participant]
    ) -> None:
        await self._db.cg_meetings.update_one(
            {"meeting_id": meeting_id},
            {
                "$set": {
                    "meeting_id": meeting_id,
                    "title": title,
                    "meeting_date": meeting_date,
                    "participants": [p.model_dump() for p in participants],
                }
            },
            upsert=True,
        )

    async def get_meeting(self, meeting_id: str) -> Optional[dict]:
        return _strip_id(await self._db.cg_meetings.find_one({"meeting_id": meeting_id}))

    async def list_meetings(self) -> list[dict]:
        return [_strip_id(d) async for d in self._db.cg_meetings.find()]

    # --- meeting record ---
    async def save_meeting_record(self, record: MeetingRecord) -> None:
        await self._db.cg_meeting_records.update_one(
            {"meeting_id": record.meeting_id},
            {"$set": record.model_dump(mode="json")},
            upsert=True,
        )

    async def get_meeting_record(self, meeting_id: str) -> Optional[MeetingRecord]:
        doc = _strip_id(await self._db.cg_meeting_records.find_one({"meeting_id": meeting_id}))
        return MeetingRecord.model_validate(doc) if doc else None

    # --- items ---
    async def save_items(self, items: list[ResolvedItem]) -> None:
        for item in items:
            await self.update_item(item)

    async def list_items(self, meeting_id: str) -> list[ResolvedItem]:
        return [
            ResolvedItem.model_validate(_strip_id(d))
            async for d in self._db.cg_items.find({"meeting_id": meeting_id}).sort("candidate_id", 1)
        ]

    async def get_item(self, candidate_id: str) -> Optional[ResolvedItem]:
        doc = _strip_id(await self._db.cg_items.find_one({"candidate_id": candidate_id}))
        return ResolvedItem.model_validate(doc) if doc else None

    async def update_item(self, item: ResolvedItem) -> None:
        await self._db.cg_items.update_one(
            {"candidate_id": item.candidate_id},
            {"$set": item.model_dump(mode="json")},
            upsert=True,
        )

    # --- review ---
    async def save_review_decision(self, decision: ReviewDecision) -> None:
        await self._db.cg_review.update_one(
            {"candidate_id": decision.candidate_id},
            {"$set": decision.model_dump(mode="json")},
            upsert=True,
        )

    async def get_review_decision(self, candidate_id: str) -> Optional[ReviewDecision]:
        doc = _strip_id(await self._db.cg_review.find_one({"candidate_id": candidate_id}))
        return ReviewDecision.model_validate(doc) if doc else None

    # --- audit (append-only: insert, never update) ---
    async def append_audit(self, event: AuditEvent) -> None:
        await self._db.cg_audit.insert_one(event.model_dump(mode="json"))

    async def list_audit(self, meeting_id: str) -> list[AuditEvent]:
        return [
            AuditEvent.model_validate(_strip_id(d))
            async for d in self._db.cg_audit.find({"meeting_id": meeting_id}).sort("created_at", 1)
        ]

    # --- issue records ---
    async def save_issue_record(self, record: GitHubIssueRecord) -> None:
        try:
            await self._db.cg_issues.insert_one(record.model_dump(mode="json"))
        except DuplicateKeyError:
            # Another approval already created an issue for this dedupe_key.
            # Swallowing this is correct and is the point of the unique
            # index: the first write wins, the second is a no-op.
            pass

    async def find_issue_by_dedupe_key(self, dedupe_key: str) -> Optional[GitHubIssueRecord]:
        doc = _strip_id(await self._db.cg_issues.find_one({"dedupe_key": dedupe_key}))
        return GitHubIssueRecord.model_validate(doc) if doc else None

    async def list_issue_records(self, meeting_id: str) -> list[GitHubIssueRecord]:
        return [
            GitHubIssueRecord.model_validate(_strip_id(d))
            async for d in self._db.cg_issues.find({"meeting_id": meeting_id})
        ]
