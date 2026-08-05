"""CommitGuard FastAPI router.

F001 scope: a single deterministic health check. Everything else (ingestion,
extraction, review, GitHub tool) is added by later features and must be
wired in here explicitly, feature by feature.
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["commitguard"])
async def commitguard_health() -> dict:
    """Deterministic liveness check for the CommitGuard subsystem.

    Does not touch Mongo, Chroma, or any LLM provider -- F001 only proves
    the module is importable and mounted, nothing more.
    """
    return {"status": "ok", "component": "commitguard"}
