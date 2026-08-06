"""Meeting history, per-meeting reports, and post-meeting actions.

Covers the promise that every meeting is separate and permanently
reviewable: distinct ids, its own report, its own list of actions taken,
and the ability to approve work from a past meeting long after it ended.
"""
from __future__ import annotations

import base64

FAKE_AUDIO = base64.b64encode(b"pretend-webm").decode()


def _candidate(client, meeting_id: str, index: int = 0) -> dict:
    return client.get(f"/meetings/{meeting_id}").json()["candidates"][index]


# --- meeting identity ------------------------------------------------------


def test_each_upload_gets_its_own_meeting_id(client, upload):
    a = upload("confirmed_commitment.txt", title="Standup A")["meeting_id"]
    b = upload("confirmed_commitment.txt", title="Standup B")["meeting_id"]

    assert a != b
    assert a.startswith("nm-") and b.startswith("nm-")


def test_two_live_sessions_never_share_an_id(client):
    """The previous implementation derived ids from id(websocket) and
    collided ~100% of the time on consecutive sockets."""
    ids = []
    for _ in range(4):
        with client.websocket_connect("/live") as ws:
            ws.send_json(
                {
                    "type": "start",
                    "title": "Live",
                    "meeting_date": "2026-08-05",
                    "participants": ["Arjun", "Rohit"],
                    "consent_acknowledged": True,
                }
            )
            ids.append(ws.receive_json()["meeting_id"])

    assert len(set(ids)) == 4, f"live meeting ids collided: {ids}"


def test_meetings_stay_separate(client, upload):
    """One meeting's items must never appear under another."""
    a = upload("confirmed_commitment.txt", title="A")["meeting_id"]
    b = upload("code_switched.txt", title="B", participants="Arjun\nPriya")["meeting_id"]

    items_a = client.get(f"/meetings/{a}").json()["candidates"]
    items_b = client.get(f"/meetings/{b}").json()["candidates"]

    assert {i["candidate_id"] for i in items_a}.isdisjoint({i["candidate_id"] for i in items_b})
    assert all(i["meeting_id"] == a for i in items_a)
    assert all(i["meeting_id"] == b for i in items_b)


# --- history ---------------------------------------------------------------


def test_history_lists_every_meeting_with_counts(client, upload):
    upload("confirmed_commitment.txt", title="First")
    upload("code_switched.txt", title="Second", participants="Arjun\nPriya")

    history = client.get("/meetings").json()
    assert len(history) == 2
    titles = {m["title"] for m in history}
    assert titles == {"First", "Second"}

    row = next(m for m in history if m["title"] == "First")
    assert row["action_items"] >= 1
    assert row["issues_created"] == 0
    assert row["has_record"] is True
    assert row["segments"] == 2


def test_history_reflects_actions_taken(client, upload, tracker):
    meeting_id = upload("confirmed_commitment.txt")["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]
    client.post(f"/review/candidates/{cid}/approve", json={"reviewer": "vyas"})

    row = next(m for m in client.get("/meetings").json() if m["meeting_id"] == meeting_id)
    assert row["issues_created"] == 1
    assert row["reviewed"] == 1


# --- report ----------------------------------------------------------------


def test_report_is_available_for_a_past_meeting(client, upload):
    meeting_id = upload("confirmed_commitment.txt", title="Sprint standup")["meeting_id"]
    report = client.get(f"/meetings/{meeting_id}/report").json()

    assert report["meeting_id"] == meeting_id
    assert report["title"] == "Sprint standup"
    assert report["executive_summary"]
    assert len(report["action_items"]) == 1
    assert report["action_items"][0]["owner_name"] == "Rohit"
    assert report["speaker_stats"], "talk time should be computed from the stored transcript"


def test_report_updates_after_an_approval(client, upload):
    """A report opened later must reflect work approved since."""
    meeting_id = upload("confirmed_commitment.txt")["meeting_id"]
    assert client.get(f"/meetings/{meeting_id}/report").json()["actions_taken"] == []

    cid = _candidate(client, meeting_id)["candidate_id"]
    client.post(f"/review/candidates/{cid}/approve", json={"reviewer": "vyas"})

    report = client.get(f"/meetings/{meeting_id}/report").json()
    assert len(report["actions_taken"]) == 1
    assert report["actions_taken"][0]["effect"] == "github_issue"
    assert report["action_items"][0]["actions"][0]["status"] == "created"


def test_report_records_a_refusal_not_just_successes(client, upload):
    meeting_id = upload("cancelled_commitment.txt")["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]
    client.post(f"/review/candidates/{cid}/approve", json={})  # refused by the gate

    report = client.get(f"/meetings/{meeting_id}/report").json()
    assert any(a["status"] == "refused" for a in report["actions_taken"])


def test_markdown_report_downloads(client, upload):
    meeting_id = upload("confirmed_commitment.txt", title="Sprint standup")["meeting_id"]
    response = client.get(f"/meetings/{meeting_id}/report.md")

    assert response.status_code == 200
    assert "# Sprint standup" in response.text
    assert "## Action items" in response.text


def test_report_404s_for_an_unknown_meeting(client):
    assert client.get("/meetings/nope/report").status_code == 404
    assert client.get("/meetings/nope/report.md").status_code == 404


# --- actions taken ---------------------------------------------------------


def test_actions_endpoint_lists_every_side_effect(client, upload):
    meeting_id = upload(
        "confirmed_commitment.txt",
        participants='[{"participant_id":"p-rohit","name":"Rohit","email":"r@example.com"}]',
    )["meeting_id"]
    cid = _candidate(client, meeting_id)["candidate_id"]
    client.post(
        f"/review/candidates/{cid}/approve",
        json={"effects": ["github_issue", "calendar_invite", "notification"]},
    )

    body = client.get(f"/meetings/{meeting_id}/actions").json()
    effects = {a["effect"] for a in body["actions"]}
    assert {"github_issue", "calendar_invite", "notification"} <= effects


def test_actions_endpoint_404s_for_an_unknown_meeting(client):
    assert client.get("/meetings/nope/actions").status_code == 404


# --- post-meeting approval -------------------------------------------------


def test_a_live_meeting_can_be_approved_after_it_ends(client, transcriber, tracker):
    """The whole point of live mode: capture during, act after."""
    transcriber.queue("mic", "Rohit, can you finish the API migration by Friday?")
    transcriber.queue("mic", "Rohit said yes, he will finish the API migration by Friday.")

    with client.websocket_connect("/live") as ws:
        ws.send_json(
            {
                "type": "start",
                "title": "Live standup",
                "meeting_date": "2026-08-05",
                "participants": ["Arjun", "Rohit"],
                "consent_acknowledged": True,
            }
        )
        meeting_id = ws.receive_json()["meeting_id"]
        for seq in range(2):
            ws.send_json(
                {
                    "type": "audio",
                    "track": "mic",
                    "seq": seq,
                    "offset_ms": seq * 6000,
                    "duration_ms": 6000,
                    "data": FAKE_AUDIO,
                }
            )
        ws.send_json({"type": "end"})
        for _ in range(12):
            msg = ws.receive_json()
            if msg["type"] == "ended":
                break

    # The meeting now behaves exactly like an uploaded one.
    assert msg["report"] is not None
    assert msg["report"]["source"] == "live"

    detail = client.get(f"/meetings/{meeting_id}").json()
    assert detail["candidates"]

    report = client.get(f"/meetings/{meeting_id}/report").json()
    assert report["segment_count"] == 2
    assert report["source"] == "live"


def test_transcript_is_retrievable_after_the_meeting(client, upload):
    meeting_id = upload("confirmed_commitment.txt")["meeting_id"]
    body = client.get(f"/meetings/{meeting_id}/transcript").json()

    assert body["segment_count"] == 2
    assert body["segments"][0]["speaker"] == "Arjun"
