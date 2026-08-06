"""Live meeting websocket.

Protocol (JSON messages, client -> server):

    {"type": "start",   "meeting_id": "...", "title": "...",
     "meeting_date": "2026-08-05", "participants": ["Arjun", "Priya"]}
    {"type": "segment", "speaker": "Priya", "text": "I'll send it by Friday"}
    {"type": "flush"}    force an extraction pass now
    {"type": "end"}      persist and close

Server -> client:

    {"type": "started",  ...}
    {"type": "segment",  ...}     echo, so the client renders a live feed
    {"type": "snapshot", ...}     current candidates + gate verdicts
    {"type": "ended",    ...}
    {"type": "error",    ...}

Nothing here can cause an external side effect. The session produces
candidates and gate decisions; approval remains a separate, human,
post-meeting action through /review.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api import deps
from app.api.routes.meetings import _to_domain_participants
from app.api.schemas import ParticipantIn
from app.core.config import Settings
from app.services.live import LiveSession
from app.services.pipeline import build_extractor

logger = logging.getLogger("nexvi_meets.live")
router = APIRouter(tags=["live"])


@router.websocket("/live")
async def live_session(
    websocket: WebSocket,
    repository=Depends(deps.get_repository),
    settings: Settings = Depends(deps.get_app_settings),
) -> None:
    await websocket.accept()
    session: LiveSession | None = None

    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")

            if kind == "start":
                participants = _to_domain_participants(
                    [
                        ParticipantIn(name=n) if isinstance(n, str) else ParticipantIn(**n)
                        for n in message.get("participants", [])
                    ]
                )
                if not participants:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "error": "At least one participant is required; owner "
                            "resolution fails closed without a directory.",
                        }
                    )
                    continue

                meeting_id = message.get("meeting_id") or f"live-{id(websocket) & 0xFFFFFF:06x}"
                try:
                    meeting_date = date.fromisoformat(
                        message.get("meeting_date") or date.today().isoformat()
                    )
                except ValueError:
                    await websocket.send_json(
                        {"type": "error", "error": "meeting_date must be ISO format"}
                    )
                    continue

                primary, fallback = build_extractor(settings)
                session = LiveSession(
                    meeting_id=meeting_id,
                    meeting_date=meeting_date,
                    participants=participants,
                    settings=settings,
                    extractor=primary,
                    fallback_extractor=fallback,
                )
                await repository.create_meeting(
                    meeting_id=meeting_id,
                    title=message.get("title") or "Live meeting",
                    meeting_date=meeting_date.isoformat(),
                    participants=participants,
                )
                await websocket.send_json(
                    {
                        "type": "started",
                        "meeting_id": meeting_id,
                        "extractor": getattr(primary, "name", "unknown"),
                    }
                )
                continue

            if session is None:
                await websocket.send_json(
                    {"type": "error", "error": "Send a 'start' message first."}
                )
                continue

            if kind == "segment":
                text = (message.get("text") or "").strip()
                if not text:
                    continue
                segment = session.add_segment(message.get("speaker") or "unknown", text)
                await websocket.send_json(
                    {
                        "type": "segment",
                        "segment_id": segment.segment_id,
                        "speaker": segment.speaker,
                        "text": segment.text,
                    }
                )
                if session.should_process:
                    await session.process()
                    await websocket.send_json({"type": "snapshot", **session.snapshot()})
                continue

            if kind == "flush":
                await session.process(force=True)
                await websocket.send_json({"type": "snapshot", **session.snapshot()})
                continue

            if kind == "end":
                await session.process(force=True)
                await session.persist(repository)
                await websocket.send_json(
                    {
                        "type": "ended",
                        **session.snapshot(),
                        "review_url": f"/meetings/{session.meeting_id}",
                    }
                )
                break

            await websocket.send_json({"type": "error", "error": f"unknown message type: {kind!r}"})

    except WebSocketDisconnect:
        # Persist whatever the meeting produced before the client vanished
        # -- losing a commitment because a laptop lid closed is exactly
        # the failure Nexvi.Meets exists to prevent.
        if session is not None:
            try:
                await session.process(force=True)
                await session.persist(repository)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not persist live session on disconnect: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Live session failed")
        try:
            await websocket.send_json({"type": "error", "error": str(exc)})
        except Exception:  # pragma: no cover - socket already gone
            pass
    finally:
        try:
            await websocket.close()
        except Exception:  # pragma: no cover
            pass
