from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ActionItemDraft(BaseModel):
    """Raw shape returned by groq_extract_tool, before date/owner resolution.
    resolution_agent consumes this and produces a full ActionItem."""
    text: str
    owner_raw: str
    due_date_raw: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    confidence_score: float
    evidence_ts: float | None = None


class ActionItem(BaseModel):
    """A fully resolved action item ready to be persisted to Mongo.

    ``dedupe_hash`` is the idempotency key computed by
    ``dedupe_hash_tool.compute_dedupe_hash(meeting_id, text, owner_raw)``
    and must be set by the caller before saving; it is indexed unique in
    the ``action_items`` collection so that upsert_action_item is the
    only write path.
    """
    meeting_id: str
    dedupe_hash: str
    text: str
    owner_raw: str
    owner_resolved: Optional[str] = None
    due_date: Optional[date] = None
    priority: Literal["low", "medium", "high"] = "medium"
    confidence_score: float
    status: Literal["pending_review", "approved", "rejected", "edited"] = "pending_review"