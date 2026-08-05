"""
Writes one audit_log entry per agent/human action. This is the tool every
approval, rejection, edit, and (in Phase 4) side effect goes through --
the audit trail is only as trustworthy as "everything writes through here,
nothing writes directly."
"""
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.audit import AuditLogEntry, AuditActionType


async def write_audit_entry(
    db: AsyncIOMotorDatabase,
    meeting_id: str,
    action_type: AuditActionType,
    payload: dict[str, Any],
    action_item_id: str | None = None,
    based_on: str | None = None,
    approved_by: str | None = None,
) -> str:
    entry = AuditLogEntry(
        meeting_id=meeting_id,
        action_item_id=action_item_id,
        action_type=action_type,
        payload=payload,
        based_on=based_on,
        approved_by=approved_by,
    )
    doc = entry.model_dump(by_alias=True, exclude={"id"})
    result = await db.audit_log.insert_one(doc)
    return str(result.inserted_id)


async def get_audit_log_for_meeting(db: AsyncIOMotorDatabase, meeting_id: str) -> list[dict]:
    cursor = db.audit_log.find({"meeting_id": meeting_id}).sort("timestamp", 1)
    return [doc async for doc in cursor]