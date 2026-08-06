"""Live meeting mode over the real websocket, with scripted audio.

Audio is a few fake bytes; the ScriptedTranscriber decides what those
bytes "said". That keeps the whole path — consent, base64 framing, two
tracks, attribution, tagging, diarization, finalize, persistence — under
test without a microphone, an audio fixture, or a network call.
"""
from __future__ import annotations

import base64

FAKE_AUDIO = base64.b64encode(b"pretend-this-is-webm-opus").decode()


def _start(ws, **overrides):
    payload = {
        "type": "start",
        "meeting_id": "live-demo",
        "title": "Live standup",
        "meeting_date": "2026-08-05",
        "participants": ["Arjun", "Rohit", "Priya"],
        "self_participant": "Arjun",
        "consent_acknowledged": True,
    }
    payload.update(overrides)
    ws.send_json(payload)
    return ws.receive_json()


def _audio(ws, track, seq, offset_ms=0):
    ws.send_json(
        {
            "type": "audio",
            "track": track,
            "seq": seq,
            "offset_ms": offset_ms,
            "duration_ms": 6000,
            "mime": "audio/webm",
            "data": FAKE_AUDIO,
        }
    )


def _drain(ws, want, limit=8):
    """Read until a message of the wanted type arrives."""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == want:
            return msg
    raise AssertionError(f"never received a {want!r} message")


# --- consent ---------------------------------------------------------------


def test_session_refuses_to_start_without_consent(client):
    with client.websocket_connect("/live") as ws:
        error = _start(ws, consent_acknowledged=False)
        assert error["type"] == "error"
        assert error["code"] == "consent_required"
        assert "being captured" in error["error"]


def test_consent_is_written_to_the_audit_log(client, repository):
    with client.websocket_connect("/live") as ws:
        assert _start(ws)["type"] == "started"

    events = client.get("/review/meetings/live-demo/audit").json()
    started = next(e for e in events if e["payload"].get("event") == "session_started")
    assert started["payload"]["consent_acknowledged"] is True
    assert started["stage"] == "live"


def test_participants_are_required(client):
    with client.websocket_connect("/live") as ws:
        error = _start(ws, participants=[])
        assert error["code"] == "participants_required"


# --- capture and attribution ----------------------------------------------


def test_mic_audio_is_transcribed_and_attributed_to_you(client, transcriber):
    transcriber.queue("mic", "I will finish the API migration by Friday.")
    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "mic", 0)
        segments = _drain(ws, "segments")["segments"]

    assert segments[0]["speaker"] == "Arjun"
    assert segments[0]["track"] == "mic"
    assert segments[0]["attributable"] is True
    assert "API migration" in segments[0]["text"]


def test_remote_audio_is_transcribed_but_not_attributed(client, transcriber):
    transcriber.queue("remote", "Rohit, can you finish the API migration by Friday?")
    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "remote", 0)
        segments = _drain(ws, "segments")["segments"]

    assert segments[0]["speaker"] == "Remote speaker"
    assert segments[0]["attributable"] is False


def test_a_failed_transcription_is_reported_not_invented(client):
    """No script queued -> the transcriber refuses -> the chunk is dropped."""
    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "mic", 0)
        msg = ws.receive_json()

    assert msg["type"] == "warnings"
    assert any("Dropped a mic audio chunk" in w for w in msg["warnings"])


def test_bad_base64_is_rejected_cleanly(client):
    with client.websocket_connect("/live") as ws:
        _start(ws)
        ws.send_json({"type": "audio", "track": "mic", "seq": 0, "data": "!!not base64!!"})
        error = ws.receive_json()
    assert error["type"] == "error"
    assert "base64" in error["error"]


def test_unknown_track_is_rejected(client):
    with client.websocket_connect("/live") as ws:
        _start(ws)
        ws.send_json({"type": "audio", "track": "speaker_phone", "seq": 0, "data": FAKE_AUDIO})
        error = ws.receive_json()
    assert "track must be" in error["error"]


def test_audio_before_start_is_rejected(client):
    with client.websocket_connect("/live") as ws:
        ws.send_json({"type": "audio", "track": "mic", "seq": 0, "data": FAKE_AUDIO})
        error = ws.receive_json()
    assert "start" in error["error"].lower()


# --- commitments surfacing live -------------------------------------------


def test_a_commitment_surfaces_during_the_meeting(client, transcriber):
    transcriber.queue("mic", "Rohit, can you finish the API migration by Friday?")
    transcriber.queue("mic", "Rohit said yes, I will finish the API migration by Friday.")

    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "mic", 0, offset_ms=0)
        _audio(ws, "mic", 1, offset_ms=6000)
        snapshot = _drain(ws, "snapshot")

    assert snapshot["segment_count"] == 2
    assert snapshot["candidates"], "a commitment should have surfaced"
    assert "No external action occurs without human approval" in snapshot["note"]


def test_live_mode_creates_nothing(client, transcriber, tracker, calendar):
    transcriber.queue("mic", "Rohit, can you finish the API migration by Friday?")
    transcriber.queue("mic", "Yes, I will finish the API migration by Friday.")

    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "mic", 0)
        _audio(ws, "mic", 1, offset_ms=6000)
        _drain(ws, "snapshot")
        ws.send_json({"type": "end"})
        _drain(ws, "ended", limit=10)

    assert tracker.created == []
    assert calendar.created == []


# --- speaker tagging -------------------------------------------------------


def test_tagging_a_remote_speaker_updates_the_transcript(client, transcriber):
    transcriber.queue("remote", "Rohit, can you finish the API migration by Friday?")

    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "remote", 0)
        segment = _drain(ws, "segments")["segments"][0]

        ws.send_json(
            {
                "type": "tag_speaker",
                "segment_id": segment["segment_id"],
                "participant_id": "p-priya-2",
            }
        )
        tagged = _drain(ws, "tagged")

    assert tagged["segments_updated"] == 1
    assert tagged["segments"][0]["speaker"] == "Priya"
    assert tagged["segments"][0]["speaker_confirmed"] is True


def test_tagging_an_unknown_participant_errors(client, transcriber):
    transcriber.queue("remote", "hello there")
    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "remote", 0)
        segment = _drain(ws, "segments")["segments"][0]
        ws.send_json(
            {
                "type": "tag_speaker",
                "segment_id": segment["segment_id"],
                "participant_id": "p-nobody",
            }
        )
        error = ws.receive_json()
    assert error["type"] == "error"
    assert "unknown participant" in error["error"]


def test_tagging_is_audited(client, transcriber):
    transcriber.queue("remote", "hello there")
    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "remote", 0)
        segment = _drain(ws, "segments")["segments"][0]
        ws.send_json(
            {
                "type": "tag_speaker",
                "segment_id": segment["segment_id"],
                "participant_id": "p-rohit-1",
            }
        )
        _drain(ws, "tagged")

    events = client.get("/review/meetings/live-demo/audit").json()
    assert any(e["payload"].get("event") == "speaker_tagged" for e in events)


# --- finalize --------------------------------------------------------------


def test_ending_runs_diarization_and_persists_for_review(client, transcriber, diarizer):
    from app.services.diarization import SpeakerTurn

    diarizer.turns = [SpeakerTurn("SPEAKER_00", 0, 20000)]
    transcriber.queue("remote", "Rohit, can you finish the API migration by Friday?")
    transcriber.queue("mic", "Yes, I will finish the API migration by Friday.")

    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "remote", 0, offset_ms=0)
        _audio(ws, "mic", 1, offset_ms=6000)
        ws.send_json({"type": "end"})
        ended = _drain(ws, "ended", limit=12)

    assert diarizer.calls == 1
    assert ended["review_url"] == "/meetings/live-demo"
    assert ended["executive_summary"]
    assert ended["diarization"]["engine"] == "stub"

    detail = client.get("/meetings/live-demo").json()
    assert detail["candidates"], "live candidates must reach the normal review flow"
    assert detail["candidates"][0]["review_status"] is None


def test_end_is_audited_with_counts(client, transcriber):
    transcriber.queue("mic", "Rohit, can you finish the API migration by Friday?")
    with client.websocket_connect("/live") as ws:
        _start(ws)
        _audio(ws, "mic", 0)
        ws.send_json({"type": "end"})
        _drain(ws, "ended", limit=12)

    events = client.get("/review/meetings/live-demo/audit").json()
    ended = next(e for e in events if e["payload"].get("event") == "session_ended")
    assert ended["payload"]["segments"] >= 1


def test_manual_text_entry_still_works_without_audio(client):
    """A demo must never hinge on the venue's microphone."""
    with client.websocket_connect("/live") as ws:
        _start(ws)
        ws.send_json(
            {
                "type": "text",
                "speaker": "Arjun",
                "text": "Rohit, can you finish the API migration by Friday?",
            }
        )
        _drain(ws, "segments")
        ws.send_json({"type": "text", "speaker": "Rohit", "text": "Yes, I will finish the API migration by Friday."})
        snapshot = _drain(ws, "snapshot")

    assert snapshot["candidates"]
    assert snapshot["candidates"][0]["owner_name"] == "Rohit"


# --- infrastructure failure ------------------------------------------------


def test_a_database_outage_reports_cleanly_instead_of_crashing(client, repository):
    """An Atlas IP allowlist block used to kill the whole websocket with a
    driver traceback, which told the operator nothing about the cause."""

    async def explode(**kwargs):
        raise RuntimeError(
            "SSL handshake failed: connection closed (ServerSelectionTimeoutError)"
        )

    repository.create_meeting = explode

    with client.websocket_connect("/live") as ws:
        error = _start(ws)

    assert error["type"] == "error"
    assert error["code"] == "storage_unavailable"
    assert "Network Access" in error["error"]


def test_the_session_does_not_continue_after_a_storage_failure(client, repository):
    async def explode(**kwargs):
        raise RuntimeError("mongo unreachable")

    repository.create_meeting = explode

    with client.websocket_connect("/live") as ws:
        _start(ws)
        # No session exists, so the next message must be told to start over
        # rather than operating on a half-built session.
        _audio(ws, "mic", 0)
        follow_up = ws.receive_json()

    assert follow_up["type"] == "error"
    assert "start" in follow_up["error"].lower()
