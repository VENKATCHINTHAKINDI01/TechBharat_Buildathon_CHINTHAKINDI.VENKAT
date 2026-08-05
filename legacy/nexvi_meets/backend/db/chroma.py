"""
ChromaDB embedded/persistent client — no server process required.
Collection `approved_meeting_records` is written to ONLY by
app/tools/chroma_index_tool.py, and only after the human-approval event.
Nothing else in the codebase should call .add() on this collection.
"""
import chromadb
from app.config import get_settings

_client: chromadb.PersistentClient | None = None


def get_chroma_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _client


def get_approved_records_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="approved_meeting_records",
        metadata={"description": "Approved meeting records only — written post-approval"},
    )
