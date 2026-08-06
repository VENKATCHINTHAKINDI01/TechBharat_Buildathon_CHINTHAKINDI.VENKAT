"""Multi side-effect approval, agent/tool introspection, and live mode
over the real HTTP/websocket surface.
"""
from __future__ import annotations


def _candidate(client, meeting_id: str, index: int = 0) -> dict:
    return client.get(f"/meetings/{meeting_id}").json()["candidates"][index]


# --- side effects ----------------------------------------------------------


def test_approval_defaults_to_github_only(client, upload, tracker, calendar, memory_store):
    """Approving must not quietly fan out to more systems than asked for."""
    meeting_id = upload("confirmed_commitment.txt")["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]

    body = client.post(f"/review/candidates/{cid}/approve", json={}).json()

    assert [e["effect"] for e in body["effects"]] == ["github_issue"]
    assert len(tracker.created) == 1
    assert calendar.created == []
    assert memory_store.records == {}


def test_all_four_side_effects_fire_when_requested(
    client, upload, tracker, calendar, memory_store, repository
):
    meeting_id = upload(
        "confirmed_commitment.txt",
        participants='[{"participant_id":"p-rohit","name":"Rohit","email":"rohit@example.com"},'
        '{"participant_id":"p-arjun","name":"Arjun","email":"arjun@example.com"}]',
    )["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]

    body = client.post(
        f"/review/candidates/{cid}/approve",
        json={
            "reviewer": "vyas",
            "effects": ["github_issue", "calendar_invite", "memory_index", "notification"],
        },
    ).json()

    statuses = {e["effect"]: e["status"] for e in body["effects"]}
    assert statuses == {
        "github_issue": "created",
        "calendar_invite": "created",
        "memory_index": "created",
        "notification": "created",
    }
    assert len(tracker.created) == 1
    assert len(calendar.created) == 1
    assert calendar.created[0].attendee_email == "rohit@example.com"
    assert len(memory_store.records) == 1


def test_calendar_is_skipped_honestly_when_the_owner_has_no_email(client, upload, calendar):
    meeting_id = upload("confirmed_commitment.txt")["meeting_id"]  # names only, no emails
    cid = _candidate(client, meeting_id)["candidate_id"]

    body = client.post(
        f"/review/candidates/{cid}/approve", json={"effects": ["calendar_invite"]}
    ).json()

    effect = body["effects"][0]
    assert effect["status"] == "skipped"
    assert "email" in effect["error"]
    assert calendar.created == []


def test_a_calendar_failure_does_not_undo_a_created_issue(client, upload, tracker, calendar):
    """Separate external systems; one failing must not roll back another."""
    meeting_id = upload(
        "confirmed_commitment.txt",
        participants='[{"participant_id":"p-rohit","name":"Rohit","email":"r@example.com"}]',
    )["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]
    calendar.fail_next = True

    body = client.post(
        f"/review/candidates/{cid}/approve",
        json={"effects": ["github_issue", "calendar_invite"]},
    ).json()

    statuses = {e["effect"]: e["status"] for e in body["effects"]}
    assert statuses["github_issue"] == "created"
    assert statuses["calendar_invite"] == "failed"
    assert len(tracker.created) == 1


def test_every_side_effect_is_independently_idempotent(client, upload, tracker, calendar):
    meeting_id = upload(
        "confirmed_commitment.txt",
        participants='[{"participant_id":"p-rohit","name":"Rohit","email":"r@example.com"}]',
    )["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]
    payload = {"effects": ["github_issue", "calendar_invite"]}

    client.post(f"/review/candidates/{cid}/approve", json=payload)
    second = client.post(f"/review/candidates/{cid}/approve", json=payload).json()

    statuses = {e["effect"]: e["status"] for e in second["effects"]}
    assert statuses == {
        "github_issue": "duplicate_suppressed",
        "calendar_invite": "duplicate_suppressed",
    }
    assert len(tracker.created) == 1
    assert len(calendar.created) == 1


def test_an_ineligible_candidate_fires_no_side_effect_at_all(
    client, upload, tracker, calendar, memory_store
):
    meeting_id = upload("cancelled_commitment.txt")["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]

    response = client.post(
        f"/review/candidates/{cid}/approve",
        json={"effects": ["github_issue", "calendar_invite", "memory_index", "notification"]},
    )
    assert response.status_code == 422
    assert tracker.created == []
    assert calendar.created == []
    assert memory_store.records == {}


def test_unknown_side_effect_is_rejected(client, upload):
    meeting_id = upload("confirmed_commitment.txt")["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]
    response = client.post(
        f"/review/candidates/{cid}/approve", json={"effects": ["send_carrier_pigeon"]}
    )
    assert response.status_code == 400


def test_side_effects_are_all_audited(client, upload):
    meeting_id = upload(
        "confirmed_commitment.txt",
        participants='[{"participant_id":"p-rohit","name":"Rohit","email":"r@example.com"}]',
    )["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]
    client.post(
        f"/review/candidates/{cid}/approve",
        json={"effects": ["github_issue", "calendar_invite", "memory_index", "notification"]},
    )

    stages = {e["stage"] for e in client.get(f"/review/meetings/{meeting_id}/audit").json()}
    assert {"github_create", "calendar_create", "memory_index", "notification"} <= stages


# --- introspection ---------------------------------------------------------


def test_agents_endpoint_describes_the_graph(client):
    body = client.get("/system/agents").json()
    names = [a["name"] for a in body["agents"]]
    assert names == [
        "ingestion", "normalization", "extraction",
        "validation", "resolution", "gate", "record",
    ]
    assert body["interrupt_before"] == "human_review"


def test_tools_endpoint_marks_the_side_effecting_ones(client):
    body = client.get("/system/tools").json()
    assert body["side_effecting"] == [
        "calendar_invite", "github_issue", "memory_index", "notification",
    ]
    assert len(body["tools"]) >= 15


def test_agent_run_trace_is_retrievable_after_upload(client, upload):
    meeting_id = upload("confirmed_commitment.txt")["meeting_id"]
    run = client.get(f"/system/meetings/{meeting_id}/agent-run").json()

    assert [s["agent"] for s in run["steps"]][-1] == "human_review"
    assert run["interrupted_at"] == "human_review"
    assert run["total_ms"] >= 0
    gate_step = next(s for s in run["steps"] if s["agent"] == "gate")
    assert gate_step["tools_used"] == ["safety_gate"]


def test_agent_run_404s_for_an_unknown_meeting(client):
    assert client.get("/system/meetings/nope/agent-run").status_code == 404


def test_memory_search_returns_only_approved_commitments(client, upload, memory_store):
    meeting_id = upload(
        "confirmed_commitment.txt",
        participants='[{"participant_id":"p-rohit","name":"Rohit","email":"r@example.com"}]',
    )["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]

    assert client.get("/system/memory/search?q=migration").json()["results"] == []

    client.post(f"/review/candidates/{cid}/approve", json={"effects": ["memory_index"]})
    results = client.get("/system/memory/search?q=API migration").json()["results"]

    assert len(results) == 1
    assert "migration" in results[0]["text"].lower()


# --- live mode -------------------------------------------------------------


def test_live_session_surfaces_a_commitment_and_creates_nothing(client, tracker):
    with client.websocket_connect("/live") as ws:
        ws.send_json(
            {
                "type": "start",
                "meeting_id": "live-demo",
                "title": "Live standup",
                "meeting_date": "2026-08-05",
                "participants": ["Arjun", "Rohit"],
            }
        )
        assert ws.receive_json()["type"] == "started"

        ws.send_json({"type": "segment", "speaker": "Arjun", "text": "Rohit, can you finish the API migration by Friday?"})
        assert ws.receive_json()["type"] == "segment"

        ws.send_json({"type": "segment", "speaker": "Rohit", "text": "Yes, I will finish the API migration by Friday."})
        assert ws.receive_json()["type"] == "segment"
        snapshot = ws.receive_json()

        assert snapshot["type"] == "snapshot"
        assert snapshot["eligible"] == 1
        assert snapshot["candidates"][0]["owner_name"] == "Rohit"

        ws.send_json({"type": "end"})
        ended = ws.receive_json()
        assert ended["type"] == "ended"
        assert ended["review_url"] == "/meetings/live-demo"

    # Live mode surfaced a commitment; it created nothing.
    assert tracker.created == []


def test_live_requires_participants(client):
    with client.websocket_connect("/live") as ws:
        ws.send_json({"type": "start", "participants": []})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert "participant" in error["error"].lower()


def test_live_rejects_messages_before_start(client):
    with client.websocket_connect("/live") as ws:
        ws.send_json({"type": "segment", "speaker": "A", "text": "hello"})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert "start" in error["error"].lower()


def test_live_candidates_land_in_the_normal_review_flow(client):
    with client.websocket_connect("/live") as ws:
        ws.send_json(
            {
                "type": "start",
                "meeting_id": "live-review",
                "meeting_date": "2026-08-05",
                "participants": ["Arjun", "Rohit"],
            }
        )
        ws.receive_json()
        for speaker, text in [
            ("Arjun", "Rohit, can you finish the API migration by Friday?"),
            ("Rohit", "Yes, I will finish the API migration by Friday."),
        ]:
            ws.send_json({"type": "segment", "speaker": speaker, "text": text})
            ws.receive_json()
        ws.receive_json()  # snapshot
        ws.send_json({"type": "end"})
        ws.receive_json()

    detail = client.get("/meetings/live-review").json()
    assert len(detail["candidates"]) == 1
    assert detail["candidates"][0]["review_status"] is None
