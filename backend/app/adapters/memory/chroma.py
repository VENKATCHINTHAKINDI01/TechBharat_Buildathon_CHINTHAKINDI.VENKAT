"""ChromaDB memory store (restored from the archived tree).

Uses Chroma's bundled default embedding function (all-MiniLM-L6-v2 via
onnxruntime) so no separate embedding API key is needed. The client is
persistent and local — cross-meeting memory should not require a network
hop or leak commitments to a third party.

Chroma's client is synchronous, so calls run in a thread.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime

from app.adapters.memory.base import MemoryError_
from app.core.config import Settings, get_settings
from app.domain.models import MemoryRecord

COLLECTION = "approved_commitments"

_client = None


def _get_collection(settings: Settings):
    global _client
    try:
        import chromadb
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise MemoryError_(
            "chromadb is not installed. pip install -r backend/requirements.txt"
        ) from exc

    if _client is None:
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _client.get_or_create_collection(
        name=COLLECTION,
        metadata={"description": "Human-approved commitments only"},
    )


def _to_metadata(record: MemoryRecord) -> dict:
    return {
        "candidate_id": record.candidate_id,
        "meeting_id": record.meeting_id,
        "meeting_title": record.meeting_title,
        "meeting_date": record.meeting_date,
        "owner_participant_id": record.owner_participant_id or "",
        "due_date": record.due_date.isoformat() if record.due_date else "",
        "created_at": record.created_at.isoformat(),
    }


def _from_metadata(memory_id: str, text: str, meta: dict) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        candidate_id=meta.get("candidate_id", ""),
        meeting_id=meta.get("meeting_id", ""),
        meeting_title=meta.get("meeting_title", ""),
        meeting_date=meta.get("meeting_date", ""),
        text=text,
        owner_participant_id=meta.get("owner_participant_id") or None,
        due_date=date.fromisoformat(meta["due_date"]) if meta.get("due_date") else None,
        created_at=datetime.fromisoformat(meta["created_at"])
        if meta.get("created_at")
        else datetime.utcnow(),
    )


class ChromaMemoryStore:
    name = "chroma"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _index_sync(self, record: MemoryRecord) -> None:
        collection = _get_collection(self._settings)
        # upsert, not add: re-indexing the same approved commitment must
        # not create a second memory entry.
        collection.upsert(
            ids=[record.memory_id],
            documents=[record.text],
            metadatas=[_to_metadata(record)],
        )

    async def index(self, record: MemoryRecord) -> None:
        await asyncio.to_thread(self._index_sync, record)

    def _search_sync(
        self, query: str, limit: int, exclude_meeting_id: str | None
    ) -> list[tuple[MemoryRecord, float]]:
        collection = _get_collection(self._settings)
        if collection.count() == 0:
            return []
        result = collection.query(query_texts=[query], n_results=min(limit * 2, 20))
        out: list[tuple[MemoryRecord, float]] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        dists = result.get("distances", [[]])[0]
        for memory_id, doc, meta, dist in zip(ids, docs, metas, dists):
            if exclude_meeting_id and meta.get("meeting_id") == exclude_meeting_id:
                continue
            # Chroma returns a distance; convert to a 0..1 similarity.
            out.append((_from_metadata(memory_id, doc, meta), max(0.0, 1.0 - float(dist))))
        return out[:limit]

    async def search(
        self, query: str, limit: int = 5, exclude_meeting_id: str | None = None
    ) -> list[tuple[MemoryRecord, float]]:
        return await asyncio.to_thread(self._search_sync, query, limit, exclude_meeting_id)

    def _all_sync(self) -> list[MemoryRecord]:
        collection = _get_collection(self._settings)
        got = collection.get()
        return [
            _from_metadata(i, d, m)
            for i, d, m in zip(got.get("ids", []), got.get("documents", []), got.get("metadatas", []))
        ]

    async def all_records(self) -> list[MemoryRecord]:
        return await asyncio.to_thread(self._all_sync)
