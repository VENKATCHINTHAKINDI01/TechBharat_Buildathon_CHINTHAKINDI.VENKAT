from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class Attendee(BaseModel):
    name: str
    email: str


class Meeting(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    title: str
    meeting_date: datetime
    source: Literal["live", "file"]
    status: Literal["in_progress", "ended", "reviewed"] = "in_progress"
    attendees: list[Attendee] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
