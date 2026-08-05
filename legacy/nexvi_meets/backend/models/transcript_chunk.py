from datetime import datetime
from pydantic import BaseModel, Field


class TranscriptChunk(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    meeting_id: str
    chunk_index: int
    speaker_label: str  # auto-diarized id, or self-tagged name
    raw_text: str
    normalized_text: str | None = None  # populated after Sarvam pass
    start_ts: float
    end_ts: float
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
