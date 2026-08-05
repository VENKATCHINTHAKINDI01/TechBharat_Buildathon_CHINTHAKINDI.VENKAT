from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class Notification(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    action_item_id: str
    owner_email: str
    calendar_event_id: str | None = None
    sent_at: datetime | None = None
    status: Literal["pending", "sent", "failed"] = "pending"

    class Config:
        populate_by_name = True
