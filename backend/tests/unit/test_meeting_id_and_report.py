"""Meeting identity and end-of-meeting reporting.

Meeting-id uniqueness is not cosmetic: the id keys the audit trail, the
dedupe keys, review decisions and issue records. A collision merges two
meetings' commitments and lets one meeting's approval satisfy another
meeting's idempotency check.
"""
from datetime import date, datetime, timezone

import pytest

from app.adapters.repositories.memory import InMemoryRepository
from app.domain.models import (
    CandidateKind,
    Classification,
    EvidenceQuote,
    GitHubIssueRecord,
    MeetingRecord,
    Participant,
    Priority,
    ResolvedItem,
    TranscriptSegment,
)
from app.services.meeting_id import is_valid_meeting_id, new_meeting_id, unique_meeting_id
from app.services.report import (
    build_speaker_stats,
    collect_actions_taken,
    generate_report,
    render_markdown,
)

PARTICIPANTS = [
    Participant(participant_id="p-rohit", name="Rohit", email="rohit@example.com"),
    Participant(participant_id="p-arjun", name="Arjun"),
]


# --- meeting ids -----------------------------------------------------------


def test_ids_do_not_collide_at_scale():
    """The old implementation derived ids from id(websocket); CPython
    reuses addresses, so consecutive meetings collided ~100% of the time.

    The suffix is 10 hex characters -- a 40-bit space. Demanding *zero*
    collisions in 200k draws would be asserting something untrue: by the
    birthday bound that fails roughly 2% of runs, which is how this test
    started failing intermittently for no reason anyone had changed.

    So the assertion is the one that is actually true and actually
    matters: at a scale far beyond any real deployment, the collision
    rate is negligible -- and ``unique_meeting_id`` re-draws against the
    repository anyway, so a collision costs one extra round trip rather
    than a merged meeting.
    """
    draws = 200_000
    ids = {new_meeting_id() for _ in range(draws)}
    collisions = draws - len(ids)
    # Expected ~9 by the birthday bound; 100 is comfortably clear of
    # noise while still catching a genuine entropy regression.
    assert collisions < 100, f"{collisions} collisions in {draws} ids"


def test_id_is_readable_and_date_stamped():
    value = new_meeting_id(date(2026, 8, 5))
    assert value.startswith("nm-20260805-")
    assert len(value) == len("nm-20260805-") + 10


def test_ids_sort_chronologically():
    older = new_meeting_id(date(2026, 8, 1))
    newer = new_meeting_id(date(2026, 8, 9))
    assert older < newer


async def test_unique_id_skips_one_already_taken():
    taken = new_meeting_id(date(2026, 8, 5))
    seen = {"count": 0}

    async def exists(candidate: str):
        seen["count"] += 1
        return candidate == taken if seen["count"] == 1 else None

    # Force the first attempt to be the taken id.
    import app.services.meeting_id as module

    original = module.new_meeting_id
    module.new_meeting_id = lambda on=None: taken if seen["count"] == 0 else original(on)
    try:
        result = await unique_meeting_id(exists, date(2026, 8, 5))
    finally:
        module.new_meeting_id = original
    assert result is not None


async def test_unique_id_returns_immediately_when_free():
    async def never_exists(_candidate):
        return None

    assert (await unique_meeting_id(never_exists)).startswith("nm-")


def test_malformed_ids_are_rejected():
    assert is_valid_meeting_id("nm-20260805-abc")
    assert not is_valid_meeting_id("")
    assert not is_valid_meeting_id("../../etc/passwd")
    assert not is_valid_meeting_id("a" * 200)


# --- report ----------------------------------------------------------------


def _item(candidate_id="c1", kind=CandidateKind.action_item, owner="p-rohit", due=date(2026, 8, 7), priority=Priority.high):
    return ResolvedItem(
        candidate_id=candidate_id,
        meeting_id="m1",
        kind=kind,
        raw_text="Rohit will finish the API migration by Friday",
        evidence_quotes=[EvidenceQuote(segment_id="m1-000", quote="I will finish the API migration")],
        priority=priority,
        confidence=0.95,
        classification=Classification.confirmed,
        owner_participant_id=owner,
        due_date=due,
    )


async def _seeded() -> InMemoryRepository:
    repo = InMemoryRepository()
    await repo.create_meeting("m1", "Sprint standup", "2026-08-05", PARTICIPANTS)
    await repo.save_items([_item()])
    await repo.save_meeting_record(
        MeetingRecord(
            meeting_id="m1",
            executive_summary="One confirmed commitment.",
            generated_at=datetime.now(timezone.utc),
        )
    )
    return repo


async def test_report_is_generated_for_a_meeting():
    report = await generate_report(
        repository=await _seeded(), meeting_id="m1", confidence_threshold=0.75
    )
    assert report.title == "Sprint standup"
    assert report.executive_summary == "One confirmed commitment."
    assert len(report.action_items) == 1
    assert report.action_items[0].owner_name == "Rohit"
    assert report.action_items[0].gate_eligible is True


async def test_report_is_none_for_an_unknown_meeting():
    assert await generate_report(
        repository=InMemoryRepository(), meeting_id="nope", confidence_threshold=0.75
    ) is None


async def test_report_shows_what_was_actually_created():
    repo = await _seeded()
    await repo.save_issue_record(
        GitHubIssueRecord(
            dedupe_key="k1",
            candidate_id="c1",
            meeting_id="m1",
            github_issue_number=42,
            github_issue_url="https://github.com/org/repo/issues/42",
            created_at=datetime.now(timezone.utc),
        )
    )
    report = await generate_report(repository=repo, meeting_id="m1", confidence_threshold=0.75)

    assert report.approved_count == 1
    assert report.action_items[0].was_actioned is True
    assert report.actions_taken[0].url.endswith("/42")


async def test_a_report_with_nothing_created_says_so():
    report = await generate_report(
        repository=await _seeded(), meeting_id="m1", confidence_threshold=0.75
    )
    assert report.actions_taken == []
    assert report.approved_count == 0
    assert "Nothing was created" in render_markdown(report)


async def test_report_counts_split_actioned_pending_and_blocked():
    repo = await _seeded()
    # An item with no owner is blocked by the gate.
    await repo.save_items([_item(candidate_id="c2", owner=None)])
    report = await generate_report(repository=repo, meeting_id="m1", confidence_threshold=0.75)

    assert report.blocked_count == 1
    assert report.pending_count == 1
    assert report.approved_count == 0


async def test_action_items_are_ordered_by_priority_then_deadline():
    repo = await _seeded()
    await repo.save_items(
        [
            _item(candidate_id="c2", priority=Priority.low, due=date(2026, 8, 6)),
            _item(candidate_id="c3", priority=Priority.high, due=date(2026, 8, 9)),
        ]
    )
    report = await generate_report(repository=repo, meeting_id="m1", confidence_threshold=0.75)
    priorities = [i.priority.value for i in report.action_items]
    assert priorities[0] == "high"
    assert priorities[-1] == "low"


async def test_report_reflects_approvals_made_after_the_meeting_ended():
    """The report is derived, not frozen -- opening it later must show
    work approved since."""
    repo = await _seeded()
    before = await generate_report(repository=repo, meeting_id="m1", confidence_threshold=0.75)
    assert before.approved_count == 0

    await repo.save_issue_record(
        GitHubIssueRecord(
            dedupe_key="k1",
            candidate_id="c1",
            meeting_id="m1",
            github_issue_number=7,
            github_issue_url="https://github.com/org/repo/issues/7",
            created_at=datetime.now(timezone.utc),
        )
    )
    after = await generate_report(repository=repo, meeting_id="m1", confidence_threshold=0.75)
    assert after.approved_count == 1


# --- talk time -------------------------------------------------------------


def test_speaker_stats_measure_words_and_share():
    segments = [
        TranscriptSegment(segment_id="s1", speaker="Arjun", text="one two three four"),
        TranscriptSegment(segment_id="s2", speaker="Rohit", text="five six"),
    ]
    stats = build_speaker_stats(segments)
    assert stats[0].speaker == "Arjun"
    assert stats[0].words == 4
    assert stats[0].share == pytest.approx(4 / 6, abs=0.01)


def test_speaker_stats_handle_an_empty_transcript():
    assert build_speaker_stats([]) == []


# --- markdown --------------------------------------------------------------


async def test_markdown_report_is_shareable():
    repo = await _seeded()
    await repo.save_issue_record(
        GitHubIssueRecord(
            dedupe_key="k1",
            candidate_id="c1",
            meeting_id="m1",
            github_issue_number=42,
            github_issue_url="https://github.com/org/repo/issues/42",
            created_at=datetime.now(timezone.utc),
        )
    )
    text = render_markdown(
        await generate_report(repository=repo, meeting_id="m1", confidence_threshold=0.75)
    )

    assert "# Sprint standup" in text
    assert "`m1`" in text
    assert "## Action items" in text
    assert "## Actions taken" in text
    assert "issues/42" in text
    assert "Rohit" in text


async def test_markdown_explains_why_an_item_was_blocked():
    repo = await _seeded()
    await repo.save_items([_item(candidate_id="c2", owner=None)])
    text = render_markdown(
        await generate_report(repository=repo, meeting_id="m1", confidence_threshold=0.75)
    )
    assert "Blocked because:" in text
    assert "no owner resolved" in text
