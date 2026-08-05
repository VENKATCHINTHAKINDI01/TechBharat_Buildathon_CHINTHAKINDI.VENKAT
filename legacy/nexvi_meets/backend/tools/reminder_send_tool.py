"""
Records a Notification document tied to the calendar event created for
this action item. The Calendar invite itself (sendUpdates="all") is what
actually emails the owner right now -- this tool's job is bookkeeping:
so the audit trail and notification history show a record per owner,
independent of Calendar's own delivery logs.
"""
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.models.notification import Notification


async def record_notification(
    db: AsyncIOMotorDatabase,
    action_item_id: str,
    owner_email: str,
    calendar_event_id: str,
) -> str:
    notification = Notification(
        action_item_id=action_item_id,
        owner_email=owner_email,
        calendar_event_id=calendar_event_id,
        status="sent",
        sent_at=datetime.utcnow(),
    )
    doc = notification.model_dump(by_alias=True, exclude={"id"})
    result = await db.notifications.insert_one(doc)
    return str(result.inserted_id)