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
        "component": "nexvi_meets",
    }


@router.get("/readiness")
async def readiness() -> dict:
    """Readiness: reports which real integrations are configured.

    Reports configuration, not reachability -- an unreachable Mongo shows
    up as a loud failure on the first real request rather than being
    silently swallowed here.
    """
    settings = get_settings()
    import os

    return {
        "status": "ok",
        "integrations": {
            "mongo": bool(settings.mongo_uri),
            "groq": settings.groq_enabled,
            "github": bool(settings.github_token and settings.github_repo),
            "sarvam": settings.sarvam_enabled,
            "calendar": os.path.exists(settings.google_credentials_path)
            or os.path.exists(settings.google_token_path),
            "memory": True,  # ChromaDB is local; no credential to miss
            "live_audio": settings.live_audio_enabled,
        },
        "extractor": "groq" if settings.groq_enabled else "reference",
        "normalizer": "sarvam" if settings.sarvam_enabled else "none",
        "agent_runtime": settings.agent_runtime,
        "live": {
            "audio_enabled": settings.live_audio_enabled,
            "transcriber": (
                "auto (whisper + sarvam)"
                if settings.groq_api_key and settings.sarvam_api_key
                else "whisper" if settings.groq_api_key
                else "sarvam" if settings.sarvam_api_key
                else "none"
            ),
            "diarization": settings.sarvam_enabled and settings.live_diarization_enabled,
            "chunk_seconds": settings.live_chunk_seconds,
        },
        "enabled_side_effects": settings.enabled_side_effects,
        "confidence_threshold": settings.confidence_threshold,
    }
