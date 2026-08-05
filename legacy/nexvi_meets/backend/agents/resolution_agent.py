"""
Resolution agent -- LangGraph node. Deterministically resolves each
draft action item's date and owner, computes overall confidence, and
produces full ActionItem objects with status="pending_review".

State in:  action_item_drafts, meeting_id, meeting_date, attendees
State out: resolved_action_items
"""
from datetime import datetime

from app.models.action_item import ActionItem
from app.models.meeting import Attendee
from app.tools.date_resolver_tool import resolve_due_date
from app.tools.owner_resolver_tool import resolve_owner
from app.tools.confidence_scorer_tool import compute_overall_confidence


async def resolution_agent(state: dict) -> dict:
    drafts = state["action_item_drafts"]
    meeting_id = state["meeting_id"]
    meeting_date: datetime = state["meeting_date"]
    attendees: list[Attendee] = state["attendees"]

    resolved: list[ActionItem] = []
    for draft in drafts:
        due_date_resolved = resolve_due_date(draft.due_date_raw, meeting_date)
        owner_resolved = resolve_owner(draft.owner_raw, attendees)

        overall_confidence = compute_overall_confidence(
            extraction_confidence=draft.confidence_score,
            owner_confidence=owner_resolved.confidence if owner_resolved else None,
            due_date_resolved=due_date_resolved,
            due_date_raw=draft.due_date_raw,
        )

        item = ActionItem(
            meeting_id=meeting_id,
            dedupe_hash="",  # computed in dedup_agent, once text is final
            text=draft.text,
            owner_raw=draft.owner_raw,
            owner_resolved=owner_resolved,
            due_date_raw=draft.due_date_raw,
            due_date_resolved=due_date_resolved,
            priority=draft.priority,
            confidence_score=overall_confidence,
            evidence_ts=draft.evidence_ts,
            status="pending_review",
        )
        resolved.append(item)

    return {**state, "resolved_action_items": resolved}