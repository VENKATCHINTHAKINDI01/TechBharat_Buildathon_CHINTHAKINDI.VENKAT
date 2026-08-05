"""The extraction/validation interface.

Both the deterministic reference implementation and the Groq-backed one
satisfy this single protocol, so every downstream stage -- owner/date
resolution, the safety gate, review, the GitHub tool -- is identical
regardless of which produced the candidates.

This is the seam that keeps the non-negotiable principle enforceable: an
Extractor may only ever return ``ValidatedItem`` objects. It cannot
approve anything, cannot reach the issue tracker, and cannot influence a
gate decision except through the structured fields it fills in.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models import TranscriptSegment, ValidatedItem


@runtime_checkable
class Extractor(Protocol):
    """Turns speaker-attributed transcript segments into classified,
    evidence-backed candidate items."""

    name: str

    def extract(self, segments: list[TranscriptSegment], meeting_id: str) -> list[ValidatedItem]:
        ...


class ExtractionError(RuntimeError):
    """Raised when an extractor cannot produce a usable result.

    Callers are expected to handle this explicitly (e.g. fall back to the
    deterministic extractor) rather than let a partial or invented result
    through -- per the brief, an empty answer beats a fabricated one.
    """


def drop_unsupported_evidence(
    items: list[ValidatedItem], segments: list[TranscriptSegment]
) -> list[ValidatedItem]:
    """Deterministic post-filter applied to *every* extractor's output.

    An evidence quote must be a verbatim substring of the segment it
    claims to come from. Anything else means the extractor paraphrased or
    hallucinated, and the quote cannot be shown to a reviewer as evidence.
    Unsupported quotes are dropped; an ``action_item`` left with no
    surviving evidence is dropped entirely, because the safety gate would
    block it anyway and surfacing it would just be noise.

    This runs outside the extractor on purpose: an LLM must not be trusted
    to grade its own citations.
    """
    text_by_id = {s.segment_id: s.text for s in segments}
    surviving: list[ValidatedItem] = []

    for item in items:
        good_quotes = [
            q
            for q in item.evidence_quotes
            if q.segment_id in text_by_id and q.quote and q.quote in text_by_id[q.segment_id]
        ]
        if not good_quotes and item.kind.value == "action_item":
            continue
        surviving.append(item.model_copy(update={"evidence_quotes": good_quotes}))

    return surviving
