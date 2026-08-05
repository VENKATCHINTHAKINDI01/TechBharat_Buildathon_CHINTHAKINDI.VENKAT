"""
Builds the owner-resolution roster for a meeting. Two sources, in
priority order:
  1. A Google Calendar event ID, if the meeting corresponds to a real
     invited meeting -- pulls the real attendee list (name + email).
  2. Manually entered attendees (name/email pairs typed into the upload
     form) -- the fallback for ad hoc meetings with no Calendar event,
     or for testing without hitting the Calendar API at all.
"""
from app.models.meeting import Attendee
from app.integrations.google_calendar_client import get_event_attendees


def roster_from_calendar_event(event_id: str) -> list[Attendee]:
    raw = get_event_attendees(event_id)
    return [Attendee(name=a["name"], email=a["email"]) for a in raw]


def roster_from_manual_entries(entries: list[str]) -> list[Attendee]:
    """Each entry like 'Priya Sharma <priya@x.com>' or 'priya@x.com'."""
    roster = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        if "<" in entry and ">" in entry:
            name = entry.split("<")[0].strip()
            email = entry.split("<")[1].split(">")[0].strip()
        else:
            email = entry
            name = email.split("@")[0]
        roster.append(Attendee(name=name, email=email))
    return roster


def build_roster(calendar_event_id: str | None, manual_attendees: list[str] | None) -> list[Attendee]:
    if calendar_event_id:
        return roster_from_calendar_event(calendar_event_id)
    if manual_attendees:
        return roster_from_manual_entries(manual_attendees)
    return []