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

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

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


# Typographic variants that mean the same spoken words. Whisper emits
# curly apostrophes and unicode dashes; a model quoting that text back
# very often straightens them. Treating those as "the model made it up"
# was throwing away correct citations.
_PUNCT_EQUIVALENTS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "−": "-",
    "…": "...", " ": " ",
}

_COLLAPSIBLE = re.compile(r"\s+")


def _fold(text: str) -> tuple[str, list[int]]:
    """Normalize for *comparison*, keeping a map back to the original.

    Returns the folded text plus, for each folded character, the index of
    the original character it came from. The map is what lets us recover
    the real transcript span afterwards -- so a quote that survives is
    still literally the speaker's words, never the model's rendering of
    them.
    """
    folded: list[str] = []
    origin: list[int] = []
    previous_was_space = False

    for index, char in enumerate(unicodedata.normalize("NFKC", text)):
        replacement = _PUNCT_EQUIVALENTS.get(char, char)
        if replacement.isspace():
            if previous_was_space or not folded:
                continue
            folded.append(" ")
            origin.append(index)
            previous_was_space = True
            continue
        previous_was_space = False
        for character in replacement.casefold():
            folded.append(character)
            origin.append(index)

    while folded and folded[-1] == " ":
        folded.pop()
        origin.pop()

    return "".join(folded), origin


def find_verbatim_span(quote: str, segment_text: str) -> Optional[str]:
    """Locate a quote in a segment and return the segment's own wording.

    Exact substring first, because that is the common case and costs
    nothing. Failing that, both sides are folded -- unicode normalized,
    quotes and dashes unified, whitespace collapsed, case ignored -- and
    the match is mapped back through the origin index.

    The security property is unchanged and this is the reason for the
    index map: what comes back is a span of the **segment**, so a model
    cannot smuggle text into evidence by claiming someone said it. All
    that has been relaxed is the typography of the needle, never the
    haystack.
    """
    if not quote or not segment_text:
        return None
    if quote in segment_text:
        return quote

    folded_quote, _ = _fold(quote)
    folded_segment, origin = _fold(segment_text)
    if not folded_quote:
        return None

    position = folded_segment.find(folded_quote)
    if position == -1:
        return None

    start = origin[position]
    end = origin[position + len(folded_quote) - 1]
    return segment_text[start : end + 1]


@dataclass
class EvidenceReport:
    """What the citation check actually did.

    Exists because "0 candidates" with no explanation is the worst
    possible output: indistinguishable from a quiet meeting, an LLM
    outage, and a bug. Every number here ends up in a warning, the audit
    log, or both.
    """

    items_in: int = 0
    items_out: int = 0
    quotes_kept: int = 0
    quotes_repaired: int = 0      # matched only after folding
    quotes_dropped: int = 0
    dropped_items: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    @property
    def summary(self) -> Optional[str]:
        if not self.quotes_dropped and not self.dropped_items:
            return None
        parts = []
        if self.dropped_items:
            parts.append(
                f"{len(self.dropped_items)} action item(s) dropped because none of "
                f"their quotes appear in the transcript"
            )
        if self.quotes_dropped:
            parts.append(f"{self.quotes_dropped} unsupported quote(s) removed")
        return "; ".join(parts)


def drop_unsupported_evidence(
    items: list[ValidatedItem],
    segments: list[TranscriptSegment],
    report: Optional[EvidenceReport] = None,
) -> list[ValidatedItem]:
    """Deterministic post-filter applied to *every* extractor's output.

    An evidence quote must be the speaker's actual words. Anything else
    means the extractor paraphrased or hallucinated, and the quote cannot
    be shown to a reviewer as evidence. Unsupported quotes are dropped; an
    ``action_item`` left with no surviving evidence is dropped entirely,
    because the safety gate would block it anyway.

    This runs outside the extractor on purpose: an LLM must not be trusted
    to grade its own citations.

    Pass a ``report`` to find out what happened. Silently returning an
    empty list is how a live meeting ended up showing "no candidates
    extracted" with nothing to debug.
    """
    text_by_id = {s.segment_id: s.text for s in segments}
    surviving: list[ValidatedItem] = []
    report = report if report is not None else EvidenceReport()
    report.items_in += len(items)

    for item in items:
        good_quotes = []
        for quote in item.evidence_quotes:
            span = find_verbatim_span(quote.quote, text_by_id.get(quote.segment_id, ""))
            if span is None:
                report.quotes_dropped += 1
                if len(report.examples) < 3:
                    report.examples.append(
                        f"{quote.segment_id}: {quote.quote[:80]!r} is not in that segment"
                    )
                continue
            if span != quote.quote:
                report.quotes_repaired += 1
            report.quotes_kept += 1
            # Store the transcript's own wording, not the model's.
            good_quotes.append(quote.model_copy(update={"quote": span}))

        if not good_quotes and item.kind.value == "action_item":
            report.dropped_items.append(item.raw_text)
            continue
        surviving.append(item.model_copy(update={"evidence_quotes": good_quotes}))

    report.items_out += len(surviving)
    return surviving
