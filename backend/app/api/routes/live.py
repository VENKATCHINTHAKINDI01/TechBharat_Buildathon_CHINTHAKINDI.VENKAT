"""Live meeting websocket — audio in, commitments out.

Protocol (JSON, client -> server):

    {"type":"start", "title":"...", "meeting_date":"2026-08-05",
     "participants":["Arjun","Priya"], "self_participant":"Arjun",
     "consent_acknowledged":true}

    {"type":"audio", "track":"mic"|"remote", "seq":0,
     "offset_ms":0, "duration_ms":6000,
     "mime":"audio/webm", "data":"<base64>"}

    {"type":"text",  "speaker":"Arjun", "text":"..."}   manual entry
    {"type":"tag_speaker", "segment_id":"...", "participant_id":"..."}
    {"type":"flush"}      force an extraction pass now
    {"type":"end"}        diarize, re-extract, persist, close

Server -> client: ``started``, ``segments``, ``snapshot``, ``tagged``,
``finalizing``, ``ended``, ``error``.

Audio is base64 inside JSON rather than binary frames. A binary frame
carries no metadata, so a separate header message would have to be
correlated with it — and with two tracks interleaving, that correlation
is exactly the kind of thing that breaks under load during a demo. The
~33% encoding overhead on a 50KB chunk every six seconds is a fair price
for a self-describing message.

Nothing here can cause an external side effect. The session produces
candidates and gate decisions; approval remains a separate, human,
post-meeting action through ``/review``.
"""
from __future__ import annotations

import base64
import binascii
import logging
from datetime import date

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.adapters.transcription.base import AudioChunk
from app.api import deps
from app.api.routes.meetings import _to_domain_participants
from app.api.schemas import ParticipantIn
from app.core.config import Settings
from app.domain.models import AuditStage
from app.services.audit import AuditLogger
from app.services.live import ConsentRequired, LiveSession
from app.services.meeting_record import synthesize_meeting_record
from app.services.pipeline import build_extractor

logger = logging.getLogger("nexvi_meets.live")
router = APIRouter(tags=["live"])

MAX_CHUNK_BYTES = 8 * 1024 * 1024  # a 6s Opus chunk is ~50KB; 8MB is a generous ceiling


@router.websocket("/live")
async def live_session(
    websocket: WebSocket,
    repository=Depends(deps.get_repository),
    settings: Settings = Depends(deps.get_app_settings),
    transcriber=Depends(deps.get_transcriber),
    diarizer=Depends(deps.get_diarizer),
) -> None:
    await websocket.accept()
    session: LiveSession | None = None
    audit: AuditLogger | None = None

    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")

            # ---------------- start ----------------
            if kind == "start":
                if not message.get("consent_acknowledged"):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "consent_required",
                            "error": (
                                "Everyone in the meeting must know it is being captured. "
                                "Acknowledge consent before starting."
                            ),
                        }
                    )
                    continue

                participants = _to_domain_participants(
                    [
                        ParticipantIn(name=p) if isinstance(p, str) else ParticipantIn(**p)
                        for p in message.get("participants", [])
                    ]
                )
                if not participants:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "participants_required",
                            "error": (
                                "At least one participant is required; owner resolution "
                                "fails closed without a directory."
                            ),
                        }
                    )
                    continue

                try:
                    meeting_date = date.fromisoformat(
                        message.get("meeting_date") or date.today().isoformat()
                    )
                except ValueError:
                    await websocket.send_json(
                        {"type": "error", "error": "meeting_date must be ISO format"}
                    )
                    continue

                meeting_id = message.get("meeting_id") or f"live-{id(websocket) & 0xFFFFFF:06x}"
                self_name = (message.get("self_participant") or "").strip().casefold()
                self_id = next(
                    (p.participant_id for p in participants if p.name.casefold() == self_name),
                    participants[0].participant_id,
                )

                primary, fallback = build_extractor(settings)
                session = LiveSession(
                    meeting_id=meeting_id,
                    meeting_date=meeting_date,
                    participants=participants,
                    settings=settings,
                    extractor=primary,
                    fallback_extractor=fallback,
                    transcriber=transcriber,
                    diarizer=diarizer,
                    self_participant_id=self_id,
                )
                session.acknowledge_consent(message.get("consent_note"))

                # A database outage is an operator problem, not a crash.
                # Without this the whole websocket dies on a driver
                # exception and the UI shows "Live session failed" with no
                # hint that the real cause is an IP allowlist.
                try:
                    await repository.create_meeting(
                        meeting_id=meeting_id,
                        title=message.get("title") or "Live meeting",
                        meeting_date=meeting_date.isoformat(),
                        participants=participants,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error("Could not create the live meeting: %s", exc)
                    session = None
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "storage_unavailable",
                            "error": (
                                "Could not reach the database, so the meeting cannot be "
                                "recorded. If this is MongoDB Atlas, the most likely cause "
                                "is that this machine's IP is not in Network Access. "
                                f"Details: {exc}"
                            ),
                        }
                    )
                    continue

                audit = AuditLogger(repository, meeting_id)
                await audit.record(
                    AuditStage.live,
                    {
                        "event": "session_started",
                        "consent_acknowledged": True,
                        "consent_note": session.consent_note,
                        "participants": [p.name for p in participants],
                        "self_participant_id": self_id,
                        "transcriber": getattr(transcriber, "name", "unknown"),
                        "extractor": getattr(primary, "name", "unknown"),
                    },
                )

                await websocket.send_json(
                    {
                        "type": "started",
                        "meeting_id": meeting_id,
                        "transcriber": getattr(transcriber, "name", "unknown"),
                        "extractor": getattr(primary, "name", "unknown"),
                        "audio_enabled": settings.live_audio_enabled,
                        "chunk_seconds": settings.live_chunk_seconds,
                        "participants": [
                            {"participant_id": p.participant_id, "name": p.name}
                            for p in participants
                        ],
                    }
                )
                continue

            if session is None:
                await websocket.send_json(
                    {"type": "error", "error": "Send a 'start' message first."}
                )
                continue

            # ---------------- audio ----------------
            if kind == "audio":
                try:
                    raw = base64.b64decode(message.get("data") or "", validate=True)
                except (binascii.Error, ValueError):
                    await websocket.send_json(
                        {"type": "error", "error": "audio payload is not valid base64"}
                    )
                    continue
                if len(raw) > MAX_CHUNK_BYTES:
                    await websocket.send_json({"type": "error", "error": "audio chunk too large"})
                    continue
                if not raw:
                    continue

                track = message.get("track")
                if track not in ("mic", "remote"):
                    await websocket.send_json(
                        {"type": "error", "error": "track must be 'mic' or 'remote'"}
                    )
                    continue

                chunk = AudioChunk(
                    track=track,
                    seq=int(message.get("seq", 0)),
                    data=raw,
                    mime=message.get("mime") or "audio/webm",
                    offset_ms=int(message.get("offset_ms", 0)),
                    duration_ms=int(message.get("duration_ms", 0)),
                )

                try:
                    created = await session.add_audio(chunk)
                except ConsentRequired as exc:
                    await websocket.send_json(
                        {"type": "error", "code": "consent_required", "error": str(exc)}
                    )
                    continue

                if created:
                    await websocket.send_json(
                        {"type": "segments", "segments": [s.as_dict() for s in created]}
                    )
                if session.should_process:
                    await session.process()
                    await websocket.send_json({"type": "snapshot", **session.snapshot()})
                elif session.warnings:
                    await websocket.send_json({"type": "warnings", "warnings": session.warnings})
                continue

            # ---------------- manual text ----------------
            if kind == "text":
                text = (message.get("text") or "").strip()
                if not text:
                    continue
                segment = session.add_text_segment(
                    message.get("speaker") or "unknown", text
                )
                await websocket.send_json({"type": "segments", "segments": [segment.as_dict()]})
                if session.should_process:
                    await session.process()
                    await websocket.send_json({"type": "snapshot", **session.snapshot()})
                continue

            # ---------------- speaker tagging ----------------
            if kind == "tag_speaker":
                try:
                    updated = session.tag_speaker(
                        message.get("segment_id", ""), message.get("participant_id", "")
                    )
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "error": str(exc)})
                    continue

                if audit:
                    await audit.record(
                        AuditStage.live,
                        {
                            "event": "speaker_tagged",
                            "segment_id": message.get("segment_id"),
                            "participant_id": message.get("participant_id"),
                            "segments_updated": updated,
                        },
                    )
                # Re-extract: a segment that said "Remote speaker" may now
                # name a real owner, which can unblock an item.
                await session.reprocess_all()
                await websocket.send_json(
                    {"type": "tagged", "segments_updated": updated, **session.snapshot()}
                )
                continue

            if kind == "flush":
                await session.process(force=True)
                await websocket.send_json({"type": "snapshot", **session.snapshot()})
                continue

            # ---------------- end ----------------
            if kind == "end":
                await websocket.send_json(
                    {"type": "finalizing", "step": "refining speakers"}
                )
                result = await session.refine_speakers()
                if audit:
                    await audit.record(
                        AuditStage.live,
                        {
                            "event": "diarization",
                            "engine": result.engine,
                            "speakers": result.speakers,
                            "error": result.error,
                        },
                    )

                await websocket.send_json({"type": "finalizing", "step": "extracting"})
                await session.reprocess_all()
                await session.persist(repository)

                record = synthesize_meeting_record(
                    session.meeting_id, list(session.items_by_key.values())
                )
                await repository.save_meeting_record(record)
                if audit:
                    await audit.record(
                        AuditStage.live,
                        {
                            "event": "session_ended",
                            "segments": len(session.segments),
                            "candidates": len(session.items_by_key),
                            "eligible": session.eligible_count,
                            "unattributed_segments": session.unattributed_count,
                        },
                    )

                await websocket.send_json(
                    {
                        "type": "ended",
                        **session.snapshot(include_segments=500),
                        "executive_summary": record.executive_summary,
                        "review_url": f"/meetings/{session.meeting_id}",
                    }
                )
                break

            await websocket.send_json({"type": "error", "error": f"unknown message type: {kind!r}"})

    except WebSocketDisconnect:
        # Persist whatever the meeting produced before the client vanished.
        # Losing a commitment because a laptop lid closed is exactly the
        # failure this product exists to prevent.
        if session is not None:
            try:
                await session.process(force=True)
                await session.persist(repository)
                logger.info("Persisted live session %s after disconnect", session.meeting_id)
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
