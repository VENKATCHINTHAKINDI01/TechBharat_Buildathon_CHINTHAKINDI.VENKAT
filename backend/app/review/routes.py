"""
Review endpoints -- the human-in-the-loop gate. Every action item sits
at status="pending_review" after Phase 2's pipeline runs; these endpoints
are the ONLY way its status changes, and every change writes an audit
log entry. Nothing here calls Calendar/ChromaDB yet -- that hookup is
Phase 4's action_agent, triggered from the approve endpoint once it exists.

Items are addressed by dedupe_hash (not Mongo _id) since it's already
the unique, stable identifier the rest of the pipeline uses.
"""
from datetime import datetime
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.mongo import get_db
from app.tools.audit_log_tool import write_audit_entry

router = APIRouter()


def _serialize(doc: dict) -> dict:
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


class ApproveRequest(BaseModel):
    approved_by: str = "demo_reviewer"


class RejectRequest(BaseModel):
    approved_by: str = "demo_reviewer"
    reason: str | None = None


class EditRequest(BaseModel):
    approved_by: str = "demo_reviewer"
    text: str | None = None
    owner_raw: str | None = None
    due_date_resolved: datetime | None = None
    priority: Literal["low", "medium", "high"] | None = None


@router.get("/meetings/{meeting_id}")
async def get_meeting_for_review(meeting_id: str):
    """Everything the review screen needs in one call: meeting info,
    latest structured record, and all action items for this meeting."""
    db = get_db()

    meeting = await db.meetings.find_one({"_id": ObjectId(meeting_id)})
    if not meeting:
        raise HTTPException(404, "Meeting not found")

    record = await db.structured_records.find_one(
        {"meeting_id": meeting_id}, sort=[("version", -1)]
    )
    items_cursor = db.action_items.find({"meeting_id": meeting_id})
    items = [_serialize(doc) async for doc in items_cursor]

    return {
        "meeting": _serialize(meeting),
        "structured_record": _serialize(record) if record else None,
        "action_items": items,
    }


@router.post("/action-items/{dedupe_hash}/approve")
async def approve_action_item(dedupe_hash: str, body: ApproveRequest):
    db = get_db()
    item = await db.action_items.find_one({"dedupe_hash": dedupe_hash})
    if not item:
        raise HTTPException(404, "Action item not found")

    now = datetime.utcnow()
    await db.action_items.update_one(
        {"dedupe_hash": dedupe_hash},
        {"$set": {"status": "approved", "approved_at": now, "approved_by": body.approved_by}},
    )

    await write_audit_entry(
        db,
        meeting_id=item["meeting_id"],
        action_type="item_approved",
        payload={"dedupe_hash": dedupe_hash, "text": item["text"]},
        action_item_id=dedupe_hash,
        based_on=item.get("evidence_ts"),
        approved_by=body.approved_by,
    )

    # Phase 4: fire the gated side effects now that approval is recorded.
    from app.agents.action_agent import run_action_agent
    from app.agents.notification_agent import run_notification_agent

    meeting = await db.meetings.find_one({"_id": ObjectId(item["meeting_id"])})
    item["approved_by"] = body.approved_by  # so action_agent's audit entries attribute correctly

    action_result = await run_action_agent(db, item, meeting)
    notification_result = await run_notification_agent(db, item, action_result["calendar_event_id"])

    if action_result["calendar_event_id"]:
        await db.action_items.update_one(
            {"dedupe_hash": dedupe_hash},
            {"$set": {"calendar_event_id": action_result["calendar_event_id"]}},
        )

    return {
        "status": "approved",
        "dedupe_hash": dedupe_hash,
        "calendar_event_id": action_result["calendar_event_id"],
        "notified": notification_result["notified"],
        "errors": action_result["errors"],
    }


@router.post("/action-items/{dedupe_hash}/reject")
async def reject_action_item(dedupe_hash: str, body: RejectRequest):
    db = get_db()
    item = await db.action_items.find_one({"dedupe_hash": dedupe_hash})
    if not item:
        raise HTTPException(404, "Action item not found")

    await db.action_items.update_one(
        {"dedupe_hash": dedupe_hash},
        {"$set": {"status": "rejected", "approved_by": body.approved_by}},
    )

    await write_audit_entry(
        db,
        meeting_id=item["meeting_id"],
        action_type="item_rejected",
        payload={"dedupe_hash": dedupe_hash, "reason": body.reason},
        action_item_id=dedupe_hash,
        approved_by=body.approved_by,
    )

    return {"status": "rejected", "dedupe_hash": dedupe_hash}


@router.patch("/action-items/{dedupe_hash}")
async def edit_action_item(dedupe_hash: str, body: EditRequest):
    """Edits are logged with the changed fields only -- not the whole
    document -- so the audit entry answers "what did the reviewer
    change" directly, without a diff."""
    db = get_db()
    item = await db.action_items.find_one({"dedupe_hash": dedupe_hash})
    if not item:
        raise HTTPException(404, "Action item not found")

    changes = body.model_dump(exclude={"approved_by"}, exclude_none=True)
    if not changes:
        raise HTTPException(400, "No fields to update")

    changes["status"] = "edited"
    await db.action_items.update_one({"dedupe_hash": dedupe_hash}, {"$set": changes})

    await write_audit_entry(
        db,
        meeting_id=item["meeting_id"],
        action_type="item_edited",
        payload={"dedupe_hash": dedupe_hash, "changed_fields": changes},
        action_item_id=dedupe_hash,
        approved_by=body.approved_by,
    )

    return {"status": "edited", "dedupe_hash": dedupe_hash, "changed_fields": list(changes.keys())}


@router.get("/meetings/{meeting_id}/audit-log")
async def get_audit_log(meeting_id: str):
    from app.tools.audit_log_tool import get_audit_log_for_meeting
    db = get_db()
    entries = await get_audit_log_for_meeting(db, meeting_id)
    return [_serialize(e) for e in entries]