"""
Calls Groq (Llama 3.3 70B) to turn the normalized transcript into a
structured draft: executive summary, decisions, open questions, risks,
and a list of raw action items (owner/date NOT yet resolved -- that's
resolution_agent's job).

Uses JSON mode so the model is constrained to valid JSON; schema_validator_tool
does the actual Pydantic validation afterward -- this tool's only job is
getting a JSON string back from Groq.
"""
from groq import Groq
from app.config import get_settings

_client: Groq | None = None

EXTRACTION_SYSTEM_PROMPT = """You are a precise meeting-minutes extraction engine.
Given a meeting transcript, output ONLY a JSON object with this exact shape:

{
  "executive_summary": "two to three sentence summary",
  "decisions": ["decision 1", "decision 2"],
  "open_questions": ["question 1"],
  "risks": ["risk or blocker 1"],
  "action_items": [
    {
      "text": "what needs to be done",
      "owner_raw": "name as mentioned in the transcript, exactly as spoken",
      "due_date_raw": "relative date phrase as spoken, e.g. 'by next Friday', or null if none given",
      "priority": "low" | "medium" | "high",
      "confidence_score": 0.0 to 1.0,
      "evidence_ts": null
    }
  ]
}

Rules:
- Never invent facts, owners, or dates not present in the transcript.
- If no due date was mentioned for an item, use null for due_date_raw -- do not guess.
- confidence_score reflects YOUR certainty this is a genuine commitment, not just a mention.
- Output valid JSON only. No markdown fences, no commentary.
"""


def _get_client() -> Groq:
    global _client
    if _client is None:
        settings = get_settings()
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def extract_structured_json(normalized_transcript: str) -> str:
    """Returns the raw JSON string from Groq. Raises on API failure --
    the caller (extraction_agent) decides how to handle that as a
    graceful-failure case rather than swallowing it here."""
    settings = get_settings()
    client = _get_client()
    completion = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": normalized_transcript},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return completion.choices[0].message.content


def extract_structured_json_stream(normalized_transcript: str):
    """Streaming variant for the Chrome-ext-style 'visible progress within
    2s' feel in the review UI. Yields text deltas; caller accumulates and
    parses once the stream ends."""
    settings = get_settings()
    client = _get_client()
    stream = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": normalized_transcript},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta