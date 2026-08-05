from datetime import datetime
from pydantic import BaseModel, Field


class StructuredRecord(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    meeting_id: str
    version: int = 1  # increments on each rolling-window pass in live mode
    executive_summary: str
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
