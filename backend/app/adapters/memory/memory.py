"""In-memory memory store -- test double only.

Uses token-overlap similarity rather than embeddings so tests are
deterministic and need no model download.
"""
from __future__ import annotations

from app.domain.models import MemoryRecord

_STOP = {"the", "a", "an", "to", "by", "for", "of", "and", "will", "up", "is"}


def _tokens(text: str) -> set[str]:
    return {
        w.strip(".,!?;:").lower()
        for w in text.split()
        if w.strip(".,!?;:").lower() not in _STOP and len(w) > 2
    }


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class InMemoryMemoryStore:
    name = "memory_store"

    def __init__(self) -> None:
        self.records: dict[str, MemoryRecord] = {}

    async def index(self, record: MemoryRecord) -> None:
        self.records[record.memory_id] = record

    async def search(
        self, query: str, limit: int = 5, exclude_meeting_id: str | None = None
    ) -> list[tuple[MemoryRecord, float]]:
        scored = [
            (r, similarity(query, r.text))
            for r in self.records.values()
            if not exclude_meeting_id or r.meeting_id != exclude_meeting_id
        ]
        scored = [(r, s) for r, s in scored if s > 0]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:limit]

    async def all_records(self) -> list[MemoryRecord]:
        return list(self.records.values())
