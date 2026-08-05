"""
Extraction agent -- LangGraph node. Calls Groq on the normalized
transcript and validates the result. On failure, sets state["error"]
instead of raising past the graph -- graph.py checks this and routes
to an error-terminal state rather than crashing, satisfying the
"graceful failure" requirement (say so, don't hallucinate a summary).

State in:  normalized_transcript, meeting_id
State out: structured_record, action_item_drafts  (or: error)
"""
from app.tools.groq_extract_tool import extract_structured_json
from app.tools.schema_validator_tool import validate_extraction, ExtractionValidationError


async def extraction_agent(state: dict) -> dict:
    try:
        raw_json = extract_structured_json(state["normalized_transcript"])
        record, drafts = validate_extraction(raw_json, state["meeting_id"])
    except ExtractionValidationError as exc:
        return {**state, "error": f"Extraction failed validation: {exc}"}
    except Exception as exc:  # noqa: BLE001 -- Groq API errors, network, etc.
        return {**state, "error": f"Extraction call failed: {exc}"}

    return {
        **state,
        "structured_record": record,
        "action_item_drafts": drafts,
    }