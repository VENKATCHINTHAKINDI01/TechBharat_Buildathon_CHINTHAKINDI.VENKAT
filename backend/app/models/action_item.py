class ActionItemDraft(BaseModel):
    """Raw shape returned by groq_extract_tool, before date/owner resolution.
    resolution_agent consumes this and produces a full ActionItem."""
    text: str
    owner_raw: str
    due_date_raw: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    confidence_score: float
    evidence_ts: float | None = None