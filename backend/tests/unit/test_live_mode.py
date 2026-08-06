"""Live meeting mode.

Two properties matter: the same commitment heard twice must not become
two candidates, and nothing may be created without post-meeting approval.
"""
from app.adapters.repositories.memory import InMemoryRepository
from app.core.config import Settings
from app.domain.models import Participant
from app.services.extraction.reference import ReferenceExtractor
from app.services.live import LiveSession
from tests.conftest import MEETING_DATE

PARTICIPANTS = [
    Participant(participant_id="p-arjun", name="Arjun"),
    Participant(participant_id="p-rohit", name="Rohit"),
]


def _session(**overrides) -> LiveSession:
    settings = Settings(confidence_threshold=0.75, live_min_new_segments=2, **overrides)
    return LiveSession(
        meeting_id="live1",
        meeting_date=MEETING_DATE,
        participants=PARTICIPANTS,
        settings=settings,
        extractor=ReferenceExtractor(),
    )


def test_segments_get_stable_increasing_ids():
    session = _session()
    a = session.add_segment("Arjun", "Rohit, can you finish the migration by Friday?")
    b = session.add_segment("Rohit", "Yes, I will finish the migration by Friday.")
    assert a.segment_id == "live1-L0000"
    assert b.segment_id == "live1-L0001"
    assert len(session.segments) == 2


def test_processing_waits_until_enough_new_segments_arrive():
    session = _session()
    session.add_segment("Arjun", "Rohit, can you finish it by Friday?")
    assert session.should_process is False
    session.add_segment("Rohit", "Yes, I will finish it by Friday.")
    assert session.should_process is True


async def test_a_commitment_is_surfaced_mid_meeting():
    session = _session()
    session.add_segment("Arjun", "Rohit, can you finish the API migration by Friday?")
    session.add_segment("Rohit", "Yes, I will finish the API migration by Friday.")
    items = await session.process()

    assert len(items) == 1
    assert items[0].owner_participant_id == "p-rohit"
    assert session.eligible_count == 1


async def test_reprocessing_the_same_speech_does_not_duplicate_the_commitment():
    """The rolling window deliberately overlaps; dedupe absorbs the cost."""
    session = _session()
    session.add_segment("Arjun", "Rohit, can you finish the API migration by Friday?")
    session.add_segment("Rohit", "Yes, I will finish the API migration by Friday.")

    first = await session.process(force=True)
    second = await session.process(force=True)
    third = await session.process(force=True)

    assert len(first) == len(second) == len(third) == 1
    assert first[0].candidate_id == third[0].candidate_id


async def test_a_later_pass_revises_rather_than_appends():
    session = _session()
    session.add_segment("Arjun", "Rohit, can you finish the API migration by Friday?")
    await session.process(force=True)
    before = len(session.items_by_key)

    session.add_segment("Rohit", "Yes, I will finish the API migration by Friday.")
    await session.process(force=True)

    # The commitment became confirmed; it did not become a second item.
    assert len(session.items_by_key) == before
    assert list(session.items_by_key.values())[0].classification.value == "confirmed"


async def test_snapshot_states_that_live_mode_never_acts():
    session = _session()
    session.add_segment("Arjun", "Rohit, can you finish it by Friday?")
    session.add_segment("Rohit", "Yes, I will finish it by Friday.")
    await session.process()
    snapshot = session.snapshot()

    assert "No external action occurs without human approval" in snapshot["note"]
    assert snapshot["eligible"] == 1
    assert snapshot["candidates"][0]["evidence"]
    assert "gate" in snapshot["candidates"][0]


async def test_empty_session_processes_without_error():
    assert await _session().process(force=True) == []


async def test_session_persists_candidates_for_post_meeting_review():
    session = _session()
    session.add_segment("Arjun", "Rohit, can you finish the API migration by Friday?")
    session.add_segment("Rohit", "Yes, I will finish the API migration by Friday.")
    await session.process(force=True)

    repository = InMemoryRepository()
    await session.persist(repository)
    stored = await repository.list_items("live1")
    assert len(stored) == 1
    # Still unapproved: live mode surfaces, it does not act.
    assert await repository.get_review_decision(stored[0].candidate_id) is None
    assert await repository.list_issue_records("live1") == []
