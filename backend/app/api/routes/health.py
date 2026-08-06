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


async def _probe_mongo(settings) -> dict:
    """Actually ping MongoDB.

    Configuration and reachability are different failures, and confusing
    them wastes real time: a set MONGO_URI that cannot connect (Atlas IP
    allowlist, bad password, no network) looks identical to a working one
    until the first write. This says which it is, with the reason.
    """
    if not settings.mongo_uri:
        return {"configured": False, "connected": False, "detail": "MONGO_URI is not set"}

    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=3000)
        try:
            await client.admin.command("ping")
            return {"configured": True, "connected": True, "detail": "ping ok"}
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        reason = str(exc)
        hint = ""
        lowered = reason.lower()
        if "ssl handshake" in lowered or "serverselectiontimeout" in lowered:
            hint = (
                " Most likely this machine's IP is not allowed in Atlas -> Network Access. "
                "Add your current IP (curl -s https://api.ipify.org)."
            )
        elif "auth" in lowered:
            hint = " The username or password in MONGO_URI looks wrong."
        return {
            "configured": True,
            "connected": False,
            "detail": f"{type(exc).__name__}: {reason[:300]}{hint}",
        }


@router.get("/readiness")
async def readiness() -> dict:
    """Readiness: what is configured, and whether the database answers.

    The Mongo probe is a real ping with a short timeout. Everything else
    reports configuration only -- an unreachable GitHub or Groq surfaces
    as a loud, actionable failure at the point of use.
    """
    settings = get_settings()
    import os

    mongo = await _probe_mongo(settings)

    return {
        "status": "ok" if mongo["connected"] or not mongo["configured"] else "degraded",
        "mongo": mongo,
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
