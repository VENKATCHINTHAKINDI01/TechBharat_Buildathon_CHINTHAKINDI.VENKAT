"""In-memory calendar client -- test double only.

Records invites instead of sending them. Not selectable at runtime;
`app/api/deps.py` only ever constructs the real Google client.
"""
from __future__ import annotations

from itertools import count

from app.adapters.calendar.base import CalendarError, CalendarInvite, CreatedEvent


class InMemoryCalendarClient:
    name = "memory_calendar"

    def __init__(self) -> None:
        self.created: list[CalendarInvite] = []
        self._counter = count(1)
        self.fail_next = False

    async def create_invite(self, invite: CalendarInvite) -> CreatedEvent:
        if self.fail_next:
            self.fail_next = False
            raise CalendarError("simulated calendar failure")
        if invite.due_date is None:
            raise CalendarError("refusing to create an invite without a resolved due date")
        self.created.append(invite)
        n = next(self._counter)
        return CreatedEvent(event_id=f"evt-{n}", html_link=f"https://calendar.example/evt-{n}")
