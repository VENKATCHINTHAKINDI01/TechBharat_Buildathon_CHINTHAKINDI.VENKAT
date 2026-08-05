"""
Validates the raw JSON string from groq_extract_tool against Pydantic
schemas. This is the enforcement point for "structured output, not
hallucinated prose" -- if the LLM's JSON doesn't match the shape, we
fail loudly here rather than pass garbage downstream.
"""
import json
from pydantic import ValidationError

from app.models.structured_record import StructuredRecord
from app.models.action_item import ActionItemDraft


class ExtractionValidationError(Exception):
    """Raised when Groq's output doesn't match the expected schema.
    The caller should mark the meeting with an error state and surface
    it honestly in the review UI -- never silently drop it or fabricate
    a fallback summary (this is the "graceful failure" requirement)."""


def validate_extraction(raw_json: str, meeting_id: str) -> tuple[StructuredRecord, list[ActionItemDraft]]:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ExtractionValidationError(f"Groq output was not valid JSON: {exc}") from exc

    try:
        record = StructuredRecord(
            meeting_id=meeting_id,
            executive_summary=data["executive_summary"],
            decisions=data.get("decisions", []),
            open_questions=data.get("open_questions", []),
            risks=data.get("risks", []),
        )
        drafts = [ActionItemDraft(**item) for item in data.get("action_items", [])]
    except (ValidationError, KeyError, TypeError) as exc:
        raise ExtractionValidationError(f"Extraction JSON did not match schema: {exc}") from exc

    return record, drafts