"""
Action agent -- fires the approval-gated side effects: personalized
Calendar invite + ChromaDB index. This is called directly from the
approve endpoint for now (not yet a LangGraph interrupt-resume node --
see graph.py's Phase 2 note). Every effect here writes its own audit
log entry, per action, so the trail shows exactly what fired and why.

Called only after review/routes.py has already recorded the approval.
"""
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.tools.calendar_tool import create_personal_invite
from app.tools.chroma_index_tool import index_approved_item
from app.tools.audit_log_tool import write_audit_entry


async def run_action_agent(db: AsyncIOMotorDatabase, item: dict, meeting: dict) -> dict:
    """item and meeting are plain Mongo docs (already fetched by the caller).
    Returns {"calendar_event_id": str | None, "errors": list[str]}."""
    errors = []
    calendar_event_id = None

    owner = item.get("owner_resolved")
    if owner is None:
        errors.append("Cannot create calendar invite: owner is unresolved. Resolve the owner via edit before approving, or this item is skipped.")
    else:
        try:
            event = create_personal_invite(
                owner_name=owner["name"],
                owner_email=owner["email"],
                action_text=item["text"],
                meeting_title=meeting["title"],
                due_date=item.get("due_date_resolved"),
            )
            calendar_event_id = event["id"]
            await write_audit_entry(
                db,
                meeting_id=item["meeting_id"],
                action_type="calendar_invite_created",
                payload={"event_id": calendar_event_id, "attendee": owner["email"], "text": item["text"]},
                action_item_id=item["dedupe_hash"],
                approved_by=item.get("approved_by"),
            )
        except Exception as exc:  # noqa: BLE001 -- Calendar API failure shouldn't crash approval
            errors.append(f"Calendar invite failed: {exc}")

    try:
        index_approved_item(
            meeting_id=item["meeting_id"],
            dedupe_hash=item["dedupe_hash"],
            text=item["text"],
            meeting_title=meeting["title"],
            meeting_date=str(meeting.get("meeting_date", "")),
        )
        await write_audit_entry(
            db,
            meeting_id=item["meeting_id"],
            action_type="chroma_indexed",
            payload={"dedupe_hash": item["dedupe_hash"]},
            action_item_id=item["dedupe_hash"],
            approved_by=item.get("approved_by"),
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Chroma indexing failed: {exc}")

    return {"calendar_event_id": calendar_event_id, "errors": errors}