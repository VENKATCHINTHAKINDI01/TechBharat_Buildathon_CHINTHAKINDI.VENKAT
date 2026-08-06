"""Nexvi.Meets FastAPI application factory."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters.trackers.base import IssueTrackerError
from app.api.routes import health, live, meetings, review, system
from app.core.config import MissingCredentialError, get_settings

logger = logging.getLogger("nexvi_meets")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "Evidence-backed meeting commitment agent. The LLM interprets the "
            "meeting; deterministic code decides whether an external action is "
            "allowed. No GitHub issue is created without a passing safety gate "
            "and an explicit human approval of the exact payload."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health.router)
    application.include_router(meetings.router)
    application.include_router(review.router)
    application.include_router(system.router)
    application.include_router(live.router)

    @application.exception_handler(IssueTrackerError)
    async def _tracker_failed(_request: Request, exc: IssueTrackerError) -> JSONResponse:
        """A failed side effect is reported as a failure, never silently
        swallowed or reported as success. The audit event was already
        written by the approval service before this handler ran."""
        # Lead with what actually went wrong. "The tracker rejected the
        # request" alone sent an operator hunting through server logs for
        # an error the API already had in hand.
        return JSONResponse(
            status_code=502,
            content={
                "detail": {
                    "message": f"Nothing was created. {exc}",
                    "error": str(exc),
                }
            },
        )

    @application.exception_handler(MissingCredentialError)
    async def _missing_credential(
        _request: Request, exc: MissingCredentialError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": {"message": "Integration is not configured.", "error": str(exc)}},
        )

    @application.on_event("startup")
    async def _startup() -> None:
        # Index creation is idempotent and cheap; the unique index on
        # nm_issues.dedupe_key is what enforces duplicate suppression, so
        # a failure here is loud rather than silent.
        if not settings.mongo_uri:
            logger.warning(
                "MONGO_URI is not set - persistence will fail on first request. "
                "See backend/.env.example."
            )
            return
        try:
            from app.adapters.repositories.mongo import MongoRepository

            await MongoRepository().ensure_indexes()
            logger.info("Mongo indexes ensured on database %s", settings.mongo_db_name)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not ensure Mongo indexes: %s", exc)

    return application


app = create_app()
