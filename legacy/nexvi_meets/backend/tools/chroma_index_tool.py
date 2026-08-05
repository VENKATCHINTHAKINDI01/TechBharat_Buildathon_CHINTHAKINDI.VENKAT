"""
Writes to the `approved_meeting_records` ChromaDB collection. This is the
ONLY function in the codebase that calls .add() on that collection --
called by action_agent, and only after approval, per the fixed diagram
(ChromaDB indexes post-approval only, not on every extraction draft).

Uses Chroma's bundled default embedding function (all-MiniLM-L6-v2 via
onnxruntime) -- no separate embedding API key needed.
"""
from app.db.chroma import get_approved_records_collection


def index_approved_item(
    meeting_id: str,
    dedupe_hash: str,
    text: str,
    meeting_title: str,
    meeting_date: str,
) -> None:
    collection = get_approved_records_collection()
    collection.add(
        ids=[dedupe_hash],
        documents=[text],
        metadatas=[{
            "meeting_id": meeting_id,
            "meeting_title": meeting_title,
            "meeting_date": meeting_date,
        }],
    )


def search_approved_records(query: str, n_results: int = 5) -> list[dict]:
    """Phase 5+ (P2 stretch: searchable meeting history) will expose this
    via a /search endpoint. Present now so the collection has a documented
    read path, not just a write path."""
    collection = get_approved_records_collection()
    results = collection.query(query_texts=[query], n_results=n_results)
    return results