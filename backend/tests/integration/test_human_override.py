"""A reviewer overruling the model.

The extractor reads "Everyone should finish by the weekend" as a
suggestion, which is reasonable -- nobody individually committed. But
someone who was in the room may know Arjun took it. Before this, they had
no way to say so: there was no classification edit, and even correcting
owner AND date left the model's low score holding the item under the
threshold. A dead end, not caution.

The gate itself is unchanged. All six rules still apply; a human is now
simply able to satisfy them.
"""
from __future__ import annotations

def _upload_vague(client, tmp_path=None):
    """`vague_suggestion.txt` is "Someone should probably clean up the
    staging environment" -- a suggestion with no owner and no date, the
    same shape as the group statements a real extractor produces from
    "Everyone should finish by the weekend"."""
    from tests.conftest import FIXTURES

    response = client.post(
        "/meetings",
        files={
            "file": (
                "vague.txt",
                (FIXTURES / "vague_suggestion.txt").read_bytes(),
                "text/plain",
            )
        },
        data={
            "title": "Standup",
            "meeting_date": "2026-08-05",
            "participants": '[{"participant_id":"p-arjun","name":"Arjun","email":"a@x.com"},'
            '{"participant_id":"p-rohit","name":"Rohit"}]',
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["meeting_id"]


def _first(client, meeting_id):
    return client.get(f"/meetings/{meeting_id}").json()["candidates"][0]


def test_a_vague_group_statement_starts_blocked(client):
    """This is correct behaviour, not the bug -- nobody named committed."""
    meeting_id = _upload_vague(client)
    candidate = _first(client, meeting_id)
    assert candidate["gate"]["eligible"] is False
    assert any("not 'confirmed'" in r for r in candidate["gate"]["reasons"])


def test_a_reviewer_can_confirm_it_and_then_approve(client, tracker):
    """The path that did not exist before."""
    meeting_id = _upload_vague(client)
    cid = _first(client, meeting_id)["candidate_id"]

    patch = client.patch(
        f"/review/candidates/{cid}",
        json={
            "reviewer": "vyas",
            "classification": "confirmed",
            "owner_participant_id": "p-arjun",
            "due_date": "2026-08-10",
        },
    )
    assert patch.status_code == 200, patch.text

    updated = _first(client, meeting_id)
    assert updated["gate"]["eligible"] is True, updated["gate"]["reasons"]

    approve = client.post(f"/review/candidates/{cid}/approve", json={"reviewer": "vyas"})
    assert approve.status_code == 200, approve.text
    assert len(tracker.created) == 1


def test_confirming_alone_is_not_enough_without_an_owner(client):
    """The other five rules still hold. This is an override of the
    model's reading, not a bypass of the gate."""
    meeting_id = _upload_vague(client)
    cid = _first(client, meeting_id)["candidate_id"]

    client.patch(f"/review/candidates/{cid}", json={"classification": "confirmed"})
    candidate = _first(client, meeting_id)

    assert candidate["gate"]["eligible"] is False
    assert any("no owner" in r for r in candidate["gate"]["reasons"])


def test_a_human_confirmation_lifts_the_confidence_score(client):
    """Previously: 0.40 extraction + perfect owner/date still scored 0.70,
    under the 0.75 threshold. A reviewer could do everything right and
    stay blocked."""
    meeting_id = _upload_vague(client)
    cid = _first(client, meeting_id)["candidate_id"]
    before = _first(client, meeting_id)["confidence"]

    client.patch(
        f"/review/candidates/{cid}",
        json={
            "classification": "confirmed",
            "owner_participant_id": "p-arjun",
            "due_date": "2026-08-10",
        },
    )
    after = _first(client, meeting_id)["confidence"]

    assert after > before
    assert after >= 0.75


def test_the_override_is_audited_as_a_human_decision(client):
    meeting_id = _upload_vague(client)
    cid = _first(client, meeting_id)["candidate_id"]
    client.patch(
        f"/review/candidates/{cid}",
        json={"reviewer": "vyas", "classification": "confirmed"},
    )

    events = client.get(f"/review/meetings/{meeting_id}/audit").json()
    edit = next(e for e in events if e["payload"].get("outcome") == "edited")
    assert edit["payload"]["human_override"] is True
    assert edit["payload"]["reviewer"] == "vyas"
    assert edit["payload"]["changed_fields"]["classification"] == "confirmed"


def test_a_reviewer_can_also_downgrade_a_confirmed_item(client, upload):
    """Override works both directions -- a model that was too eager can be
    corrected down, not only up."""
    meeting_id = upload("confirmed_commitment.txt")["meeting_id"]
    cid = _first(client, meeting_id)["candidate_id"]
    assert _first(client, meeting_id)["gate"]["eligible"] is True

    client.patch(f"/review/candidates/{cid}", json={"classification": "rejected"})
    assert _first(client, meeting_id)["gate"]["eligible"] is False


def test_an_invalid_classification_is_rejected(client, upload):
    meeting_id = upload("confirmed_commitment.txt")["meeting_id"]
    cid = _first(client, meeting_id)["candidate_id"]
    response = client.patch(f"/review/candidates/{cid}", json={"classification": "definitely"})
    assert response.status_code == 400
    assert "classification must be one of" in response.text


def test_cancelled_items_still_cannot_be_approved_by_confirming(client, upload, tracker):
    """A reviewer can say 'this was actually committed'. They cannot make
    the gate forget the six rules -- reclassifying to 'cancelled' still
    blocks, and the tracker stays untouched."""
    meeting_id = upload("cancelled_commitment.txt")["meeting_id"]
    cid = _first(client, meeting_id)["candidate_id"]

    client.patch(f"/review/candidates/{cid}", json={"classification": "cancelled"})
    response = client.post(f"/review/candidates/{cid}/approve", json={})

    assert response.status_code == 422
    assert tracker.created == []
