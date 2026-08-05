"""F008 acceptance tests -- see docs/acceptance-tests.md#f008.

Meeting date fixed at 2026-08-05 (a Wednesday) for every test so results
are reproducible regardless of when the suite is actually run.
"""
from datetime import date

from app.commitguard.models.schemas import DateResolutionMethod
from app.commitguard.resolvers.date_resolver import resolve_date

MEETING_DATE = date(2026, 8, 5)  # Wednesday


def test_plain_weekday_resolves_to_upcoming_occurrence():
    d, method = resolve_date("Friday", MEETING_DATE)
    assert d == date(2026, 8, 7)
    assert method == DateResolutionMethod.relative


def test_by_prefix_and_next_weekday_phrasing():
    d, method = resolve_date("by next Friday", MEETING_DATE)
    assert d == date(2026, 8, 7)
    assert method == DateResolutionMethod.relative


def test_eod_and_time_of_day_are_stripped():
    d, method = resolve_date("by EOD Thursday", MEETING_DATE)
    assert d == date(2026, 8, 6)
    assert method == DateResolutionMethod.relative


def test_in_two_weeks():
    d, method = resolve_date("in two weeks", MEETING_DATE)
    assert d == date(2026, 8, 19)
    assert method == DateResolutionMethod.relative


def test_code_switched_date_phrase_with_telugu_postposition():
    # "Monday morning ki" from the code_switched fixture ("Monday morning
    # ki పంపిస్తాను" -- "ki" is a Telugu postposition meaning "to/for").
    d, method = resolve_date("Monday morning ki", MEETING_DATE)
    assert d == date(2026, 8, 10)
    assert method == DateResolutionMethod.relative


def test_telugu_varaku_until_postposition():
    d, method = resolve_date("Monday varaku", MEETING_DATE)
    assert d == date(2026, 8, 10)
    assert method == DateResolutionMethod.relative


def test_absolute_date_detected_as_absolute():
    d, method = resolve_date("August 10", MEETING_DATE)
    assert d == date(2026, 8, 10)
    assert method == DateResolutionMethod.absolute


def test_unresolvable_phrase_returns_none_not_a_guess():
    d, method = resolve_date("sometime later", MEETING_DATE)
    assert d is None
    assert method == DateResolutionMethod.unresolved


def test_vague_phrase_returns_none():
    d, method = resolve_date("soonish", MEETING_DATE)
    assert d is None
    assert method == DateResolutionMethod.unresolved


def test_none_mention_is_unresolved():
    d, method = resolve_date(None, MEETING_DATE)
    assert d is None
    assert method == DateResolutionMethod.unresolved


def test_empty_mention_is_unresolved():
    d, method = resolve_date("   ", MEETING_DATE)
    assert d is None
    assert method == DateResolutionMethod.unresolved
