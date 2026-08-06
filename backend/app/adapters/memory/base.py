"""Cross-meeting memory seam.

Only **approved** commitments are indexed. The memory store is a record
of what a team actually committed to, never of what a model guessed, so
"what did we agree last sprint?" cannot be answered with a hallucination
that was rejected in review.

Backs the brief's stretch goal: carry forward open items for a recurring
meeting and flag commitments that have slipped.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models import MemoryRecord


class MemoryError_(RuntimeError):
    """Memory backend failure. Never fatal to an approval — indexing is a
    convenience, and losing it must not roll back a created issue."""


@runtime_checkable
class MemoryStore(Protocol):
    name: str

    async def index(self, record: MemoryRecord) -> None: ...

    async def search(
        self, query: str, limit: int = 5, exclude_meeting_id: str | None = None
    ) -> list[tuple[MemoryRecord, float]]: ...

    async def all_records(self) -> list[MemoryRecord]: ...
