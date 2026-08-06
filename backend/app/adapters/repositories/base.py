"""Repository protocol -- the persistence seam.

Two implementations satisfy it: ``MongoRepository`` (real, used at
runtime) and ``InMemoryRepository`` (used by the test suite so CI needs
no database). Every method here is deliberately explicit rather than a
generic ``save(collection, doc)``, so the storage layer cannot be used to
smuggle in an undocumented collection or an unaudited write.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

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


@runtime_checkable
class Repository(Protocol):
    # --- meetings ---
    async def create_meeting(
        self, meeting_id: str, title: str, meeting_date: str, participants: list[Participant]
    ) -> None: ...

    async def get_meeting(self, meeting_id: str) -> Optional[dict]: ...

    async def list_meetings(self) -> list[dict]: ...

    # --- meeting record (F011b) ---
    async def save_meeting_record(self, record: MeetingRecord) -> None: ...

    async def get_meeting_record(self, meeting_id: str) -> Optional[MeetingRecord]: ...

    # --- candidates ---
    async def save_items(self, items: list[ResolvedItem]) -> None: ...

    async def list_items(self, meeting_id: str) -> list[ResolvedItem]: ...

    async def get_item(self, candidate_id: str) -> Optional[ResolvedItem]: ...

    async def update_item(self, item: ResolvedItem) -> None: ...

    # --- review decisions (F012) ---
    async def save_review_decision(self, decision: ReviewDecision) -> None: ...

    async def get_review_decision(self, candidate_id: str) -> Optional[ReviewDecision]: ...

    # --- audit (F011) ---
    async def append_audit(self, event: AuditEvent) -> None: ...

    async def list_audit(self, meeting_id: str) -> list[AuditEvent]: ...

    # --- issue records / idempotency (F014, F015) ---
    async def save_issue_record(self, record: GitHubIssueRecord) -> None: ...

    async def find_issue_by_dedupe_key(self, dedupe_key: str) -> Optional[GitHubIssueRecord]: ...

    async def list_issue_records(self, meeting_id: str) -> list[GitHubIssueRecord]: ...

    # --- calendar events (second gated side effect) ---
    async def save_calendar_event(self, record: CalendarEventRecord) -> None: ...

    async def find_calendar_event_by_dedupe_key(
        self, dedupe_key: str
    ) -> Optional[CalendarEventRecord]: ...

    async def list_calendar_events(self, meeting_id: str) -> list[CalendarEventRecord]: ...

    # --- notifications ---
    async def save_notification(self, record: NotificationRecord) -> None: ...

    async def list_notifications(self, meeting_id: str) -> list[NotificationRecord]: ...

    # --- agent runs (orchestration trace) ---
    async def save_agent_run(self, run: AgentRun) -> None: ...

    async def get_agent_run(self, meeting_id: str) -> Optional[AgentRun]: ...
