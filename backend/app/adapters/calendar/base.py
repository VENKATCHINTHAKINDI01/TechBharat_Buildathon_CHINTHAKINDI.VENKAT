"""Calendar integration seam (restored from the archived Nexvi.Meets tree).

A calendar invite is a *second* gated side effect alongside GitHub. It
reaches exactly one owner — the person who made the commitment — rather
than broadcasting to the room, because the point is personal
accountability, not a meeting recap.

Like every side effect, it is reachable only through the tool registry
with a passing gate decision and an explicit approval.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel


class CalendarInvite(BaseModel):
    summary: str
    description: str
    attendee_email: str
    due_date: Optional[date] = None


class CreatedEvent(BaseModel):
    event_id: str
    html_link: Optional[str] = None


class CalendarError(RuntimeError):
    """Calendar call failed. Surfaced and audited, never swallowed."""


@runtime_checkable
class CalendarClient(Protocol):
    name: str

    async def create_invite(self, invite: CalendarInvite) -> CreatedEvent: ...
