"""In-memory repository.

Used by the test suite so the whole pipeline -- including the review API
and idempotency behaviour -- can be exercised without a database. It is
not offered as a runtime option: production requires real MongoDB (see
``app/core/config.py``), because a demo that silently ran on throwaway
memory would be exactly the kind of thing the audit trail exists to
prevent.
"""
from __future__ import annotations

from typing import Optional

from app.domain.models import (
    AuditEvent,
    GitHubIssueRecord,
    MeetingRecord,
    Participant,
    ResolvedItem,
    ReviewDecision,
)


class InMemoryRepository:
    def __init__(self) -> None:
        self._meetings: dict[str, dict] = {}
        self._records: dict[str, MeetingRecord] = {}
        self._items: dict[str, ResolvedItem] = {}
        self._decisions: dict[str, ReviewDecision] = {}
        self._audit: list[AuditEvent] = []
        self._issues: dict[str, GitHubIssueRecord] = {}

    async def create_meeting(
        self, meeting_id: str, title: str, meeting_date: str, participants: list[Participant]
    ) -> None:
        self._meetings[meeting_id] = {
            "meeting_id": meeting_id,
            "title": title,
            "meeting_date": meeting_date,
            "participants": [p.model_dump() for p in participants],
        }

    async def get_meeting(self, meeting_id: str) -> Optional[dict]:
        return self._meetings.get(meeting_id)

    async def list_meetings(self) -> list[dict]:
        return list(self._meetings.values())

    async def save_meeting_record(self, record: MeetingRecord) -> None:
        self._records[record.meeting_id] = record

    async def get_meeting_record(self, meeting_id: str) -> Optional[MeetingRecord]:
        return self._records.get(meeting_id)

    async def save_items(self, items: list[ResolvedItem]) -> None:
        for item in items:
            self._items[item.candidate_id] = item

    async def list_items(self, meeting_id: str) -> list[ResolvedItem]:
        return [i for i in self._items.values() if i.meeting_id == meeting_id]

    async def get_item(self, candidate_id: str) -> Optional[ResolvedItem]:
        return self._items.get(candidate_id)

    async def update_item(self, item: ResolvedItem) -> None:
        self._items[item.candidate_id] = item

    async def save_review_decision(self, decision: ReviewDecision) -> None:
        self._decisions[decision.candidate_id] = decision

    async def get_review_decision(self, candidate_id: str) -> Optional[ReviewDecision]:
        return self._decisions.get(candidate_id)

    async def append_audit(self, event: AuditEvent) -> None:
        self._audit.append(event)

    async def list_audit(self, meeting_id: str) -> list[AuditEvent]:
        return [e for e in self._audit if e.meeting_id == meeting_id]

    async def save_issue_record(self, record: GitHubIssueRecord) -> None:
        # setdefault, not assignment: an existing dedupe_key must never be
        # overwritten -- that is the idempotency guarantee (F015).
        self._issues.setdefault(record.dedupe_key, record)

    async def find_issue_by_dedupe_key(self, dedupe_key: str) -> Optional[GitHubIssueRecord]:
        return self._issues.get(dedupe_key)

    async def list_issue_records(self, meeting_id: str) -> list[GitHubIssueRecord]:
        return [r for r in self._issues.values() if r.meeting_id == meeting_id]
