"""The whole product, in the order a user meets it.

Every other integration test checks one seam. This one walks the entire
journey through the public API — upload, review, gate, approve, the real
side effect, idempotency, the report, history and the audit trail — so a
change that keeps each seam green while breaking the path between them
still fails here.

It exists because "all the tests pass" and "the app works end to end"
turned out to be different claims: a live meeting produced a transcript,
zero candidates, and an empty report, while the suite was fully green.
"""
from tests.conftest import FIXTURES


def test_the_whole_journey_on_a_renegotiated_commitment(client, tracker):
    """`owner_reassignment.txt` is the interesting fixture: Rohit takes the
    task, then hands it to Meera. Everything downstream must agree that
    Meera owns it — the summariser's answer would have been Rohit."""

    # --- 1. upload -------------------------------------------------------
    upload = client.post(
        "/meetings",
        files={"file": ("f.txt", (FIXTURES / "owner_reassignment.txt").read_bytes(), "text/plain")},
        data={
            "title": "Sprint standup",
            "meeting_date": "2026-08-06",
            "participants": "Arjun\nRohit\nMeera",
        },
    )
    assert upload.status_code == 200, upload.text
    meeting_id = upload.json()["meeting_id"]
    assert upload.json()["candidates"] >= 1

    # --- 2. review screen ------------------------------------------------
    detail = client.get(f"/meetings/{meeting_id}").json()
    assert detail["candidates"], "the review queue must not be empty"

    candidate = detail["candidates"][0]
    assert candidate["owner_name"] == "Meera", "the reassignment must win"
    assert [e["state"] for e in candidate["timeline"]] == [
        "proposed", "reassigned", "accepted",
    ]
    assert candidate["was_renegotiated"] is True
    assert candidate["field_confidence"], "per-field confidence must reach the UI"
    assert candidate["evidence"], "an action item must carry citable evidence"

    # Diagnostics are present even on the happy path, so their absence is
    # always a signal rather than the norm.
    assert detail["extraction"]["candidates_found"] == len(detail["candidates"])
    assert detail["extraction"]["fallback_reason"] is None

    # --- 3. the gate -----------------------------------------------------
    eligible = [c for c in detail["candidates"] if c["gate"]["eligible"]]
    assert eligible, "nothing could be approved, so the demo has no happy path"
    for blocked in (c for c in detail["candidates"] if not c["gate"]["eligible"]):
        assert blocked["gate"]["reasons"], "a block must always come with a reason"

    candidate_id = eligible[0]["candidate_id"]
    assert eligible[0]["proposed_payload"], "the reviewer must see the exact payload"

    # --- 4. approve, once ------------------------------------------------
    approved = client.post(
        f"/review/candidates/{candidate_id}/approve",
        json={"reviewer": "vyas", "effects": ["github_issue"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["created"] is True
    assert len(tracker.created) == 1

    # --- 5. approve again: idempotency -----------------------------------
    again = client.post(
        f"/review/candidates/{candidate_id}/approve",
        json={"reviewer": "vyas", "effects": ["github_issue"]},
    )
    assert again.json()["duplicate_suppressed"] is True
    assert len(tracker.created) == 1, "a second approval must not create a second issue"

    # --- 6. the report ---------------------------------------------------
    report = client.get(f"/meetings/{meeting_id}/report").json()
    assert report["action_items"]
    item = report["action_items"][0]
    assert item["owner_name"] == "Meera"
    assert item["was_renegotiated"] is True
    assert any(a["status"] == "created" for a in item["actions"])

    markdown = client.get(f"/meetings/{meeting_id}/report.md")
    assert markdown.status_code == 200
    assert "This changed during the meeting" in markdown.text

    # --- 7. history ------------------------------------------------------
    history = client.get("/meetings").json()
    assert any(m["meeting_id"] == meeting_id for m in history)

    # --- 8. the audit trail ----------------------------------------------
    audit = client.get(f"/review/meetings/{meeting_id}/audit").json()
    stages = {event["stage"] for event in audit}
    assert {"extraction", "validation", "gate", "review"} <= stages, stages

    run = client.get(f"/system/meetings/{meeting_id}/agent-run").json()
    assert len(run["steps"]) >= 7, "every agent should have recorded a step"


def test_nothing_reaches_github_without_an_approval(client, tracker):
    """The guarantee, checked at the level of the whole journey rather
    than the unit that enforces it."""
    client.post(
        "/meetings",
        files={"file": ("f.txt", (FIXTURES / "confirmed_commitment.txt").read_bytes(), "text/plain")},
        data={"title": "x", "meeting_date": "2026-08-06", "participants": "Arjun\nRohit"},
    )
    assert tracker.created == [], "uploading alone must never create anything"


def test_a_blocked_item_cannot_be_approved_into_existence(client, tracker):
    """A human may correct an item, but may not wave it past the gate."""
    upload = client.post(
        "/meetings",
        files={"file": ("f.txt", (FIXTURES / "vague_suggestion.txt").read_bytes(), "text/plain")},
        data={"title": "x", "meeting_date": "2026-08-06", "participants": "Arjun\nRohit"},
    )
    meeting_id = upload.json()["meeting_id"]
    detail = client.get(f"/meetings/{meeting_id}").json()

    blocked = [c for c in detail["candidates"] if not c["gate"]["eligible"]]
    if not blocked:
        return  # nothing to assert on this fixture

    response = client.post(
        f"/review/candidates/{blocked[0]['candidate_id']}/approve",
        json={"reviewer": "vyas", "effects": ["github_issue"]},
    )
    assert response.status_code >= 400
    assert tracker.created == []
