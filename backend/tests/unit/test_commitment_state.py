"""The commitment state engine.

A commitment is something that happens over the course of a meeting, not
a fact extracted once. These tests pin the rule that makes that matter:
**any change to the terms requires fresh acceptance**. Nobody is bound to
a commitment they did not make.
"""
from datetime import date
from pathlib import Path

import pytest

from app.domain.commitment import (
    STATE_TO_CLASSIFICATION,
    CommitmentEvent,
    CommitmentState as S,
    CommitmentThread,
    FieldConfidence,
    IllegalTransition,
)
from app.services.extraction.reference import ReferenceExtractor
from app.services.ingestion.normalization import normalize
from app.services.ingestion.parser import parse_txt
from tests.conftest import FIXTURES


def _thread(*states_and_kwargs) -> CommitmentThread:
    thread = CommitmentThread(thread_id="t1", meeting_id="m1")
    for state, kwargs in states_and_kwargs:
        thread.add(CommitmentEvent(state=state, **kwargs), strict=False)
    return thread


# --- transitions -----------------------------------------------------------


def test_a_new_thread_may_only_start_in_a_sensible_state():
    empty = CommitmentThread(thread_id="t", meeting_id="m")
    assert empty.can_transition_to(S.proposed)
    assert empty.can_transition_to(S.accepted)
    # A meeting cannot open by cancelling something nobody proposed.
    assert not empty.can_transition_to(S.cancelled)
    assert not empty.can_transition_to(S.deadline_changed)


def test_an_illegal_transition_raises_in_strict_mode():
    thread = _thread((S.proposed, {}))
    with pytest.raises(IllegalTransition, match="cannot go from"):
        thread.add(CommitmentEvent(state=S.deadline_changed), strict=True)


def test_an_illegal_transition_is_dropped_for_extractor_output():
    """A confused model should not corrupt the thread or crash the meeting."""
    thread = _thread((S.proposed, {}), (S.deadline_changed, {}))
    assert [e.state for e in thread.events] == [S.proposed]


def test_a_cancelled_commitment_can_be_revived():
    """Teams do change their minds back."""
    thread = _thread((S.proposed, {}), (S.accepted, {}), (S.cancelled, {}), (S.proposed, {}))
    assert thread.current_state == S.proposed


# --- the rule that matters -------------------------------------------------


def test_accepted_is_the_only_state_that_reaches_confirmed():
    confirmed = [s for s, c in STATE_TO_CLASSIFICATION.items() if c == "confirmed"]
    assert confirmed == [S.accepted]


def test_a_reassignment_drops_out_of_confirmed_until_the_new_owner_agrees():
    thread = _thread(
        (S.proposed, {"owner_mention": "Rohit"}),
        (S.accepted, {"owner": "p-rohit"}),
        (S.reassigned, {"owner_mention": "Meera"}),
    )
    assert thread.classification == "suggestion"
    assert thread.is_settled is False

    thread.add(CommitmentEvent(state=S.accepted, owner="p-meera"), strict=False)
    assert thread.classification == "confirmed"
    assert thread.current_owner == "p-meera"


def test_a_deadline_change_drops_out_of_confirmed_until_re_agreed():
    thread = _thread(
        (S.proposed, {"date_mention": "Monday"}),
        (S.accepted, {"due_date": date(2026, 8, 10)}),
        (S.deadline_changed, {"date_mention": "Thursday"}),
    )
    assert thread.classification == "suggestion"

    thread.add(
        CommitmentEvent(state=S.accepted, due_date=date(2026, 8, 6)), strict=False
    )
    assert thread.classification == "confirmed"
    assert thread.current_due_date == date(2026, 8, 6)


def test_the_latest_owner_and_date_win():
    thread = _thread(
        (S.proposed, {"owner": "p-rohit", "due_date": date(2026, 8, 10)}),
        (S.accepted, {}),
        (S.reassigned, {"owner": "p-meera"}),
        (S.accepted, {"due_date": date(2026, 8, 6)}),
    )
    assert thread.current_owner == "p-meera"
    assert thread.current_due_date == date(2026, 8, 6)


def test_renegotiation_is_flagged():
    """A task that moved mid-meeting is exactly the kind that gets
    forgotten afterwards."""
    assert _thread((S.proposed, {}), (S.accepted, {})).was_renegotiated is False
    assert _thread((S.proposed, {}), (S.accepted, {}), (S.deadline_changed, {})).was_renegotiated
    assert _thread((S.proposed, {}), (S.reassigned, {})).was_renegotiated


# --- evidence timeline -----------------------------------------------------


def test_every_event_carries_the_line_that_caused_it():
    thread = _thread(
        (S.proposed, {"quote": "Rohit, can you finish it?", "segment_id": "s0", "actor": "Arjun", "at_ms": 14000}),
        (S.accepted, {"quote": "Yes, I will.", "segment_id": "s1", "actor": "Rohit", "at_ms": 22000}),
    )
    timeline = thread.timeline()

    assert [e["label"] for e in timeline] == ["Proposed", "Accepted"]
    assert timeline[0]["at"] == "00:14"
    assert timeline[1]["actor"] == "Rohit"
    assert timeline[1]["quote"] == "Yes, I will."
    assert all(e["segment_id"] for e in timeline)


def test_evidence_quotes_come_from_the_timeline():
    thread = _thread(
        (S.proposed, {"quote": "a", "segment_id": "s0"}),
        (S.accepted, {"quote": "b", "segment_id": "s1"}),
    )
    assert thread.evidence_quotes == [("s0", "a"), ("s1", "b")]


# --- per-field confidence --------------------------------------------------


def test_field_confidence_names_the_weakest_part():
    assert FieldConfidence(text=0.9, owner=0.0, date=1.0, state=1.0).weakest_field == "owner"
    assert FieldConfidence(text=0.2, owner=1.0, date=1.0, state=1.0).weakest_field == "text"


def test_an_unsettled_thread_scores_lower_on_state():
    from app.domain.models import DateResolutionMethod as D, OwnerResolutionMethod as O
    from app.services.confidence import compute_field_confidence

    settled = compute_field_confidence(
        extraction_confidence=0.9, owner_method=O.exact_match,
        date_method=D.relative, date_was_claimed=True, state_settled=True,
    )
    pending = compute_field_confidence(
        extraction_confidence=0.9, owner_method=O.exact_match,
        date_method=D.relative, date_was_claimed=True, state_settled=False,
    )
    assert settled.state > pending.state


# --- the extractor produces real timelines ---------------------------------


def _extract(fixture: str):
    segments = normalize(parse_txt((FIXTURES / fixture).read_text(encoding="utf-8")), meeting_id="m")
    return ReferenceExtractor().extract(segments, "m")


def test_a_simple_commitment_is_proposed_then_accepted():
    item = _extract("confirmed_commitment.txt")[0]
    assert [e["state"] for e in item.timeline] == ["proposed", "accepted"]
    assert item.current_state == "accepted"
    assert item.was_renegotiated is False


def test_a_deadline_change_records_all_four_turns():
    item = _extract("deadline_change.txt")[0]
    assert [e["state"] for e in item.timeline] == [
        "proposed", "accepted", "deadline_changed", "accepted",
    ]
    assert item.current_state == "accepted"
    assert item.was_renegotiated is True
    assert "Thursday" in item.raw_date_mention


def test_a_reassignment_records_who_handed_it_over():
    item = _extract("owner_reassignment.txt")[0]
    assert [e["state"] for e in item.timeline] == ["proposed", "reassigned", "accepted"]
    assert item.raw_owner_mention == "Meera"
    reassignment = next(e for e in item.timeline if e["state"] == "reassigned")
    assert reassignment["actor"] == "Rohit"
    assert "swamped" in reassignment["quote"]


def test_a_cancellation_ends_the_thread():
    item = _extract("cancelled_commitment.txt")[0]
    assert [e["state"] for e in item.timeline] == ["proposed", "accepted", "cancelled"]
    assert item.current_state == "cancelled"
    assert item.classification.value == "cancelled"
