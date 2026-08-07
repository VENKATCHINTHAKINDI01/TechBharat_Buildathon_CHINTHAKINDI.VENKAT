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


class InMemoryRepository:
    def __init__(self) -> None:
        self._meetings: dict[str, dict] = {}
        self._records: dict[str, MeetingRecord] = {}
        self._items: dict[str, ResolvedItem] = {}
        self._decisions: dict[str, ReviewDecision] = {}
        self._audit: list[AuditEvent] = []
        self._issues: dict[str, GitHubIssueRecord] = {}
        self._calendar: dict[str, CalendarEventRecord] = {}
        self._notifications: list[NotificationRecord] = []
        self._runs: dict[str, AgentRun] = {}
        self._segments: dict[str, list[dict]] = {}

    async def create_meeting(
        self, meeting_id: str, title: str, meeting_date: str, participants: list[Participant]
    ) -> None:
        self._meetings[meeting_id] = {
            "meeting_id": meeting_id,
            "title": title,
            "meeting_date": meeting_date,
            "participants": [p.model_dump() for p in participants],
        }

    async def update_participants(
        self, meeting_id: str, participants: list[Participant]
    ) -> None:
        """Replace the roster of a meeting already in progress.

        People join late, and names read off the screen only become real
        once a human confirms them. Either way the stored roster has to
        catch up, or owner resolution keeps failing for someone who is
        demonstrably in the room.
        """
        meeting = self._meetings.get(meeting_id)
        if meeting is not None:
            meeting["participants"] = [p.model_dump() for p in participants]

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

    async def delete_items(self, meeting_id: str) -> int:
        """Remove a meeting's candidates so re-analysis starts clean.

        Without this, re-extracting after tagging speakers would leave
        the previous run's items behind under their old ids, and the
        review queue would show both.
        """
        doomed = [k for k, v in self._items.items() if v.meeting_id == meeting_id]
        for key in doomed:
            del self._items[key]
        return len(doomed)

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

    # --- calendar ---
    async def save_calendar_event(self, record: CalendarEventRecord) -> None:
        self._calendar.setdefault(record.dedupe_key, record)

    async def find_calendar_event_by_dedupe_key(
        self, dedupe_key: str
    ) -> Optional[CalendarEventRecord]:
        return self._calendar.get(dedupe_key)

    async def list_calendar_events(self, meeting_id: str) -> list[CalendarEventRecord]:
        return [r for r in self._calendar.values() if r.meeting_id == meeting_id]

    # --- notifications ---
    async def save_notification(self, record: NotificationRecord) -> None:
        self._notifications.append(record)

    async def list_notifications(self, meeting_id: str) -> list[NotificationRecord]:
        return [n for n in self._notifications if n.meeting_id == meeting_id]

    # --- agent runs ---
    async def save_agent_run(self, run: AgentRun) -> None:
        self._runs[run.meeting_id] = run

    async def get_agent_run(self, meeting_id: str) -> Optional[AgentRun]:
        return self._runs.get(meeting_id)

    # --- transcript ---
    async def save_segments(self, meeting_id: str, segments: list[dict]) -> None:
        self._segments[meeting_id] = list(segments)

    async def list_segments(self, meeting_id: str) -> list[dict]:
        return list(self._segments.get(meeting_id, []))

    # --- history ---
    async def meeting_summaries(self) -> list[dict]:
        out = []
        for meeting in self._meetings.values():
            mid = meeting["meeting_id"]
            items = [i for i in self._items.values() if i.meeting_id == mid]
            out.append(
                {
                    **meeting,
                    "action_items": sum(1 for i in items if i.kind.value == "action_item"),
                    "candidates": len(items),
                    "reviewed": sum(
                        1 for i in items if self._decisions.get(i.candidate_id) is not None
                    ),
                    "issues_created": sum(
                        1 for r in self._issues.values() if r.meeting_id == mid
                    ),
                    "calendar_events": sum(
                        1 for r in self._calendar.values() if r.meeting_id == mid
                    ),
                    "segments": len(self._segments.get(mid, [])),
                    "has_record": mid in self._records,
                }
            )
        out.sort(key=lambda m: m.get("created_at") or m["meeting_id"], reverse=True)
        return out
