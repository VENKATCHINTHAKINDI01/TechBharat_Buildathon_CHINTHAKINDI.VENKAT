"""
Normalizes code-switched Hindi/Telugu/Tamil-English transcript text into
clean English, using Sarvam's /translate endpoint via the official SDK.

Reference: https://docs.sarvam.ai/api-reference/text/translate-text
Model: sarvam-translate:v1 (all 22 scheduled languages, formal mode).
Source language is left unset so Sarvam auto-detects it per segment --
this is what makes code-switched input workable without pre-splitting
by language. Verify auto-detect behavior against current docs before
the demo; fall back to explicit source_language="hi-IN" etc. per
segment if auto-detect proves unreliable on your test transcripts.
"""
from sarvamai import SarvamAI
from app.config import get_settings

_client: SarvamAI | None = None


def _get_client() -> SarvamAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = SarvamAI(api_subscription_key=settings.sarvam_api_key)
    return _client


def normalize_to_english(text: str) -> str:
    """Returns clean English text. On any API failure, returns the
    original text unchanged so the pipeline degrades gracefully instead
    of blocking extraction entirely."""
    if not text.strip():
        return text
    try:
        client = _get_client()
        response = client.translate(
            input=text,
            target_language_code="en-IN",
            model="sarvam-translate:v1",
        )
        return response.translated_text
    except Exception as exc:  # noqa: BLE001 -- degrade, don't crash the pipeline
        print(f"[sarvam_normalize_tool] normalization failed, using raw text: {exc}")
        return text


def normalize_chunks(chunks: list[dict]) -> list[dict]:
    """Mutates each chunk dict in place, adding 'normalized_text'."""
    for chunk in chunks:
        chunk["normalized_text"] = normalize_to_english(chunk["raw_text"])
    return chunks