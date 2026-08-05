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
    (meeting, text, owner) combination.

    Critical guard: if a human has already made a decision on this item
    (approved/rejected/edited), a re-extraction pass must NOT overwrite
    it. Without this, live mode's rolling window would flip an approved
    item back to pending_review on its next pass -- undoing a human
    decision is worse than a missed refinement.
    """
    existing = await db.action_items.find_one(
        {"dedupe_hash": item.dedupe_hash}, {"status": 1}
    )
    if existing and existing.get("status") in ("approved", "rejected", "edited"):
        return  # human decision stands -- do not overwrite

    doc = item.model_dump(by_alias=True, exclude={"id"})
    await db.action_items.update_one(
        {"dedupe_hash": item.dedupe_hash},
        {"$set": doc},
        upsert=True,
    )


async def get_action_items_for_meeting(db: AsyncIOMotorDatabase, meeting_id: str) -> list[dict]:
    cursor = db.action_items.find({"meeting_id": meeting_id})
    return [doc async for doc in cursor]