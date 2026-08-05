"""
The only place that writes meetings/structured_records/action_items to
Mongo. Centralizing writes here (rather than scattering db.calls across
agents) makes the idempotency guarantee auditable in one place.
"""
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.meeting import Meeting
from app.models.structured_record import StructuredRecord
from app.models.action_item import ActionItem


async def save_meeting(db: AsyncIOMotorDatabase, meeting: Meeting) -> str:
    doc = meeting.model_dump(by_alias=True, exclude={"id"})
    result = await db.meetings.insert_one(doc)
    return str(result.inserted_id)


async def save_structured_record(db: AsyncIOMotorDatabase, record: StructuredRecord) -> str:
    doc = record.model_dump(by_alias=True, exclude={"id"})
    result = await db.structured_records.insert_one(doc)
    return str(result.inserted_id)


async def upsert_action_item(db: AsyncIOMotorDatabase, item: ActionItem) -> None:
    """Insert if dedupe_hash is new; otherwise update in place -- this is
    the idempotency guarantee. Never creates a duplicate for the same
    (meeting, text, owner) combination."""
    doc = item.model_dump(by_alias=True, exclude={"id"})
    await db.action_items.update_one(
        {"dedupe_hash": item.dedupe_hash},
        {"$set": doc},
        upsert=True,
    )


async def get_action_items_for_meeting(db: AsyncIOMotorDatabase, meeting_id: str) -> list[dict]:
    cursor = db.action_items.find({"meeting_id": meeting_id})
    return [doc async for doc in cursor]