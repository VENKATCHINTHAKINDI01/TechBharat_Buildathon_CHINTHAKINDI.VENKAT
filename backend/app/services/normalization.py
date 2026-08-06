"""Code-switch normalization (Sarvam), restored with a safety redesign.

The legacy tool translated transcript text to English in place. That is
unsafe here: Nexvi.Meets's evidence quotes must be **verbatim substrings
of what was actually said**, and the safety gate blocks any item whose
citations don't survive that check. Translating in place would have
silently destroyed every quote on a code-switched transcript.

So normalization is additive, never destructive:

    segment.text            <- original, untouched, what quotes cite
    segment.normalized_text <- English rendering, extraction input only

The extractor reads ``segment.extraction_text`` (normalized if present,
original otherwise), while ``drop_unsupported_evidence`` always validates
against ``segment.text``. Comprehension improves; the audit trail cannot
weaken.

Failure is non-fatal by design: if Sarvam is unavailable, segments keep
their original text and the pipeline continues in the exact state it
would have been in without normalization at all.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol, runtime_checkable

from app.core.config import Settings, get_settings
from app.domain.models import TranscriptSegment

logger = logging.getLogger("nexvi_meets.normalization")


@runtime_checkable
class Normalizer(Protocol):
    name: str

    async def normalize(self, segments: list[TranscriptSegment]) -> list[TranscriptSegment]: ...


class NullNormalizer:
    """Used when no Sarvam key is configured. Explicit no-op rather than a
    conditional sprinkled through the pipeline."""

    name = "none"

    async def normalize(self, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        return segments


class SarvamNormalizer:
    """Translates each segment into English via Sarvam.

    Only segments that appear to contain non-Latin script or known
    code-switch markers are sent, so a fully-English standup does not pay
    for a translation round trip per line.
    """

    name = "sarvam"

    # Devanagari, Telugu, Tamil, Kannada, Malayalam, Bengali, Gurmukhi, Gujarati
    _NON_LATIN_RANGES = (
        (0x0900, 0x097F), (0x0C00, 0x0C7F), (0x0B80, 0x0BFF), (0x0C80, 0x0CFF),
        (0x0D00, 0x0D7F), (0x0980, 0x09FF), (0x0A00, 0x0A7F), (0x0A80, 0x0AFF),
    )
    # Romanized code-switch markers common in Indian standups.
    _ROMANIZED_MARKERS = (
        "chesi", "chestha", "chesthava", "chesthanu", "varaku", "cheyyi",
        "karunga", "karenge", "kar dunga", "kar dena", "hoga", "chahiye",
        "bhej", "denge", "raha", "rahe", "nahi", "haan",
    )

    def __init__(self, settings: Settings | None = None, client=None) -> None:
        self._settings = settings or get_settings()
        self._client = client

    @classmethod
    def looks_code_switched(cls, text: str) -> bool:
        for ch in text:
            code = ord(ch)
            if any(lo <= code <= hi for lo, hi in cls._NON_LATIN_RANGES):
                return True
        lowered = text.lower()
        return any(marker in lowered for marker in cls._ROMANIZED_MARKERS)

    def _get_client(self):
        if self._client is None:
            from sarvamai import SarvamAI  # imported lazily; optional dependency

            self._client = SarvamAI(api_subscription_key=self._settings.sarvam_api_key)
        return self._client

    def _translate_sync(self, text: str) -> str:
        client = self._get_client()
        response = client.translate(
            input=text,
            target_language_code="en-IN",
            model=self._settings.sarvam_model,
        )
        return getattr(response, "translated_text", text) or text

    async def normalize(self, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        out: list[TranscriptSegment] = []
        for segment in segments:
            if not self.looks_code_switched(segment.text):
                out.append(segment)
                continue
            try:
                english = await asyncio.to_thread(self._translate_sync, segment.text)
            except Exception as exc:  # noqa: BLE001 - degrade, never block the pipeline
                logger.warning(
                    "Sarvam normalization failed for %s, keeping original text: %s",
                    segment.segment_id,
                    exc,
                )
                out.append(segment)
                continue
            # model_copy, not mutation: the original object stays intact.
            out.append(segment.model_copy(update={"normalized_text": english}))
        return out


def build_normalizer(settings: Settings | None = None) -> Normalizer:
    settings = settings or get_settings()
    if settings.sarvam_api_key:
        return SarvamNormalizer(settings)
    return NullNormalizer()
