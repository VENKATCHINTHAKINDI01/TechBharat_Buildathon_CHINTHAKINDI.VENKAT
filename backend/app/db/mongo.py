"""
Async MongoDB client (motor). Import `get_db()` wherever a collection is needed.
Collections used across the app:
  meetings, transcript_chunks, structured_records,
  action_items, audit_log, notifications
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import get_settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(settings.mongo_uri)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    settings = get_settings()
    return get_client()[settings.mongo_db_name]


async def ensure_indexes() -> None:
    """Call once at startup. Idempotency depends on the unique index below."""
    db = get_db()
    await db.action_items.create_index("dedupe_hash", unique=True)
    await db.meetings.create_index("meeting_date")
    await db.audit_log.create_index("meeting_id")
