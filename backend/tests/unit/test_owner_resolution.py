"""F007 acceptance tests -- see docs/acceptance-tests.md#f007."""
from app.domain.models import OwnerResolutionMethod, Participant
from app.services.resolvers.owner import resolve_owner

ROHIT = Participant(participant_id="p-rohit", name="Rohit", aliases=["Rohit Sharma"])
MEERA = Participant(participant_id="p-meera", name="Meera", aliases=[])
PRIYA_S = Participant(participant_id="p-priya-s", name="Priya", aliases=["Priya Shah"])
PRIYA_R = Participant(participant_id="p-priya-r", name="Priya", aliases=["Priya Rao"])

DIRECTORY = [ROHIT, MEERA]
AMBIGUOUS_DIRECTORY = [PRIYA_S, PRIYA_R]


def test_exact_match_by_name():
    pid, method = resolve_owner("Rohit", DIRECTORY)
    assert pid == "p-rohit"
    assert method == OwnerResolutionMethod.exact_match


def test_exact_match_case_insensitive():
    pid, method = resolve_owner("rohit", DIRECTORY)
    assert pid == "p-rohit"
    assert method == OwnerResolutionMethod.exact_match


def test_exact_match_by_alias():
    pid, method = resolve_owner("Rohit Sharma", DIRECTORY)
    assert pid == "p-rohit"
    assert method == OwnerResolutionMethod.exact_match


def test_fuzzy_match_typo():
    pid, method = resolve_owner("Rohitt", DIRECTORY)
    assert pid == "p-rohit"
    assert method == OwnerResolutionMethod.fuzzy_match


def test_unknown_mention_is_unresolved_not_a_guess():
    pid, method = resolve_owner("Someone Else Entirely", DIRECTORY)
    assert pid is None
    assert method == OwnerResolutionMethod.unresolved


def test_none_mention_is_unresolved():
    pid, method = resolve_owner(None, DIRECTORY)
    assert pid is None
    assert method == OwnerResolutionMethod.unresolved


def test_ambiguous_owner_fixture_fails_closed():
    # Two real participants both go by "Priya" -- resolver must not guess.
    pid, method = resolve_owner("Priya", AMBIGUOUS_DIRECTORY)
    assert pid is None
    assert method == OwnerResolutionMethod.unresolved


def test_ambiguous_owner_resolves_when_alias_disambiguates():
    pid, method = resolve_owner("Priya Rao", AMBIGUOUS_DIRECTORY)
    assert pid == "p-priya-r"
    assert method == OwnerResolutionMethod.exact_match
