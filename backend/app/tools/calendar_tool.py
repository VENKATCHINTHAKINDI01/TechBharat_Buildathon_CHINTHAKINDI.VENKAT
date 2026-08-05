"""
The only tool permitted to create real Google Calendar events. Called by
action_agent, and only after approval is recorded -- this is the
"nothing fires until approved" boundary made concrete in code.
"""
from datetime import datetime, timedelta
from app.integrations.google_calendar_client import create_event


def create_personal_invite(
    owner_name: str,
    owner_email: str,
    action_text: str,
    meeting_title: str,
    due_date: datetime | None,
) -> dict:
    """Creates one event, addressed to exactly one owner. If no due date
    was resolved, defaults to tomorrow rather than silently skipping --
    an approved item with no deadline still needs to land somewhere the
    owner will see it."""
    effective_due_date = due_date or (datetime.utcnow() + timedelta(days=1))

    event = create_event(
        summary=f"Action item: {action_text[:80]}",
        description=(
            f"From meeting: {meeting_title}\n\n"
            f"Owner: {owner_name}\n"
            f"Task: {action_text}\n\n"
            f"Created by NexVi.Meets after human approval."
        ),
        attendee_email=owner_email,
        due_date=effective_due_date,
    )
    return event