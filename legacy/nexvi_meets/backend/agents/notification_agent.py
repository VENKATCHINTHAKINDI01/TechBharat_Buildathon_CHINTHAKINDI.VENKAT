"""
Notification agent -- records the per-owner notification and (scope
note in reminder_scheduler_tool) computes when a follow-up nudge would
fire. Runs after action_agent, only if a calendar event was actually
created (no event = nothing to notify about yet).
"""
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.tools.reminder_send_tool import record_notification
from app.tools.reminder_scheduler_tool import compute_reminder_time


async def run_notification_agent(
    db: AsyncIOMotorDatabase,
    item: dict,
    calendar_event_id: str | None,
) -> dict:
    if calendar_event_id is None or item.get("owner_resolved") is None:
        return {"notified": False}

    owner_email = item["owner_resolved"]["email"]
    await record_notification(
        db,
        action_item_id=item["dedupe_hash"],
        owner_email=owner_email,
        calendar_event_id=calendar_event_id,
    )

    reminder_time = compute_reminder_time(item.get("due_date_resolved"))
    return {"notified": True, "reminder_time": reminder_time}