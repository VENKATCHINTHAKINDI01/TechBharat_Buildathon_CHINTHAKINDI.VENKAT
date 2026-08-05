from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

AuditActionType = Literal[
    "calendar_invite_created",
    "chroma_indexed",
    "item_approved",
    "item_rejected",
    "item_edited",
]


class AuditLogEntry(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    meeting_id: str
    action_item_id: str | None = None
    action_type: AuditActionType
    payload: dict[str, Any]  # exact payload that was sent/stored — for judge review
    based_on: str | None = None  # evidence_ts or transcript reference
    approved_by: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
