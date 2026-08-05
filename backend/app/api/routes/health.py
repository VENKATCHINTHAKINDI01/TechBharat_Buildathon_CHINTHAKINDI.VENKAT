"""Health and readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness. Deliberately does no I/O so it stays a true liveness
    signal and not an accidental dependency check."""
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "component": "commitguard",
    }


@router.get("/readiness")
async def readiness() -> dict:
    """Readiness: reports which real integrations are configured.

    Reports configuration, not reachability -- an unreachable Mongo shows
    up as a loud failure on the first real request rather than being
    silently swallowed here.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "integrations": {
            "mongo": bool(settings.mongo_uri),
            "groq": settings.groq_enabled,
            "github": bool(settings.github_token and settings.github_repo),
        },
        "extractor": "groq" if settings.groq_enabled else "reference",
        "confidence_threshold": settings.confidence_threshold,
    }
