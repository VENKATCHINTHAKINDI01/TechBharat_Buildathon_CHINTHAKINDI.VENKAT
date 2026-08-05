"""F003: deterministic normalization of RawUtterance -> TranscriptSegment.

Purely mechanical: assigns a stable, meeting-scoped segment_id to every
utterance in transcript order. No LLM involved.
"""
from __future__ import annotations

from app.commitguard.ingestion.parser import RawUtterance
from app.commitguard.models.schemas import TranscriptSegment


def normalize(utterances: list[RawUtterance], meeting_id: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for idx, u in enumerate(utterances):
        segments.append(
            TranscriptSegment(
                segment_id=f"{meeting_id}-{idx:03d}",
                speaker=u.speaker,
                start_ms=u.start_ms,
                end_ms=u.end_ms,
                text=u.text,
            )
        )
    return segments
