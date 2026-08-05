"""
Dedup agent -- LangGraph node. Computes each item's dedupe_hash and
upserts everything (meeting, structured record, action items) to
MongoDB. This is the last node in the Phase 2 graph -- items land in
Mongo with status="pending_review", ready for Phase 3's review UI.

State in:  meeting (Meeting), structured_record, resolved_action_items, db
State out: saved_action_item_ids
"""
from app.tools.dedupe_hash_tool import compute_dedupe_hash
from app.tools.mongo_query_tool import (
    save_meeting,
    save_structured_record,
    upsert_action_item,
)


async def dedup_agent(state: dict) -> dict:
    db = state["db"]

    meeting_id = state.get("meeting_id")
    if meeting_id is None:
        meeting_id = await save_meeting(db, state["meeting"])

    record = state["structured_record"]
    record.meeting_id = meeting_id
    await save_structured_record(db, record)

    saved_ids = []
    for item in state["resolved_action_items"]:
        item.meeting_id = meeting_id
        item.dedupe_hash = compute_dedupe_hash(meeting_id, item.text, item.owner_raw)
        await upsert_action_item(db, item)
        saved_ids.append(item.dedupe_hash)

    return {**state, "meeting_id": meeting_id, "saved_action_item_ids": saved_ids}