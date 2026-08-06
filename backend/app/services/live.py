"""Live meeting mode — surface commitments as they are made.

A live session receives transcript lines over a websocket while the
meeting is happening, keeps a rolling window of recent speech, and re-runs
extraction whenever enough new material has arrived. Candidates appear in
the UI mid-meeting instead of after it.

Two properties matter more here than in the file-upload path:

**Nothing is created live.** The session produces candidates and gate
decisions only. Every side effect still requires the same human approval
afterwards — a live agent that could act autonomously would fail the
brief's "zero unapproved actions" metric by construction.

**The same commitment must not multiply.** A rolling window re-reads
overlapping speech, so the same sentence is extracted repeatedly. Each
candidate is keyed by its dedupe key, and a re-extraction *updates* the
existing candidate rather than appending a new one. That is why the window
can overlap safely: overlap improves context, and dedupe absorbs the cost.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

from app.core.config import Settings
from app.domain.models import (
    GateDecision,
    Participant,
    ResolvedItem,
    TranscriptSegment,
)
from app.domain.safety.gate import check_gate
from app.services.extraction.base import Extractor, ExtractionError, drop_unsupported_evidence
from app.services.idempotency import compute_dedupe_key
from app.services.resolvers.combine import resolve_validated_items


@dataclass
class LiveUpdate:
    """What the client receives after a processing pass."""

    kind: str  # "segment" | "candidates" | "error" | "status"
    payload: dict[str, Any] = field(default_factory=dict)


class LiveSession:
    def __init__(
        self,
        *,
        meeting_id: str,
        meeting_date: date,
        participants: list[Participant],
        settings: Settings,
        extractor: Extractor,
        fallback_extractor: Optional[Extractor] = None,
        on_update: Optional[Callable[[LiveUpdate], Any]] = None,
    ) -> None:
        self.meeting_id = meeting_id
        self.meeting_date = meeting_date
        self.participants = participants
        self.settings = settings
        self.extractor = extractor
        self.fallback_extractor = fallback_extractor or extractor
        self.on_update = on_update

        self.segments: list[TranscriptSegment] = []
        # Rolling window of recent segments. maxlen keeps memory bounded on
        # a long meeting; the full transcript is retained separately.
        self._window: deque[TranscriptSegment] = deque(maxlen=settings.live_window_seconds)
        self._since_last_pass = 0
        self._counter = 0

        # candidate identity -> item, keyed by dedupe key so the same
        # commitment heard twice updates rather than duplicates.
        self.items_by_key: dict[str, ResolvedItem] = {}
        self.gate_decisions: dict[str, GateDecision] = {}

    # --- ingestion -------------------------------------------------------

    def add_segment(self, speaker: str, text: str) -> TranscriptSegment:
        segment = TranscriptSegment(
            segment_id=f"{self.meeting_id}-L{self._counter:04d}",
            speaker=speaker.strip() or "unknown",
            text=text.strip(),
        )
        self._counter += 1
        self.segments.append(segment)
        self._window.append(segment)
        self._since_last_pass += 1
        return segment

    @property
    def should_process(self) -> bool:
        return self._since_last_pass >= self.settings.live_min_new_segments

    @property
    def window(self) -> list[TranscriptSegment]:
        return list(self._window)

    # --- processing ------------------------------------------------------

    async def process(self, force: bool = False) -> list[ResolvedItem]:
        """Run one extraction pass over the rolling window.

        Returns the full current candidate set (not just new ones), because
        a later pass can *revise* an earlier candidate — a commitment that
        was ambiguous at 00:30 may have an owner by 00:45, and the UI needs
        the corrected version, not both versions.
        """
        if not force and not self.should_process:
            return list(self.items_by_key.values())
        if not self._window:
            return []

        self._since_last_pass = 0
        window = self.window

        try:
            candidates = self.extractor.extract(window, self.meeting_id)
        except ExtractionError:
            candidates = self.fallback_extractor.extract(window, self.meeting_id)

        candidates = drop_unsupported_evidence(candidates, window)
        resolved = resolve_validated_items(candidates, self.participants, self.meeting_date)

        for item in resolved:
            key = compute_dedupe_key(self.meeting_id, item.owner_participant_id, item.raw_text)
            # Overwrite: the newest pass has the most context.
            stable = item.model_copy(update={"candidate_id": f"{self.meeting_id}-{key[:10]}"})
            self.items_by_key[key] = stable
            self.gate_decisions[stable.candidate_id] = check_gate(
                stable, self.settings.confidence_threshold
            )

        return list(self.items_by_key.values())

    # --- output ----------------------------------------------------------

    @property
    def eligible_count(self) -> int:
        return sum(1 for d in self.gate_decisions.values() if d.eligible)

    def snapshot(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "segments": len(self.segments),
            "candidates": [
                {
                    "candidate_id": item.candidate_id,
                    "raw_text": item.raw_text,
                    "classification": item.classification.value,
                    "owner_participant_id": item.owner_participant_id,
                    "owner_name": next(
                        (
                            p.name
                            for p in self.participants
                            if p.participant_id == item.owner_participant_id
                        ),
                        None,
                    ),
                    "due_date": item.due_date.isoformat() if item.due_date else None,
                    "priority": item.priority.value,
                    "confidence": item.confidence,
                    "evidence": [q.model_dump() for q in item.evidence_quotes],
                    "gate": {
                        "eligible": self.gate_decisions[item.candidate_id].eligible,
                        "reasons": self.gate_decisions[item.candidate_id].reasons,
                    },
                }
                for item in self.items_by_key.values()
            ],
            "eligible": self.eligible_count,
            # Stated in every payload so a demo viewer cannot mistake live
            # surfacing for live acting.
            "note": "Live mode surfaces candidates only. No external action occurs without human approval after the meeting.",
        }

    async def persist(self, repository) -> None:
        """Save the live session's results so the normal review flow can
        pick them up once the meeting ends."""
        items = list(self.items_by_key.values())
        if not items:
            return
        await repository.save_items(items)
