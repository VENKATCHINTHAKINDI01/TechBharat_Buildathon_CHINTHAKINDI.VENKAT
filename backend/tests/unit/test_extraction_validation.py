"""F005/F006 acceptance tests -- see docs/acceptance-tests.md#f005 / #f006.

Runs the deterministic reference pipeline (app.services.extraction.reference)
over every fixture in tests/fixtures/ and checks the classification and
evidence-linking guarantees that matter for commitment integrity -- not
exact wording, since this is a pattern-based reference implementation, not
an LLM.
"""
from pathlib import Path

from app.services.extraction.reference import extract_and_validate
from app.services.ingestion.normalization import normalize
from app.services.ingestion.parser import parse_txt
from app.domain.models import Classification

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def _load(name: str, meeting_id: str = "m1"):
    content = (FIXTURES / name).read_text(encoding="utf-8")
    utterances = parse_txt(content)
    segments = normalize(utterances, meeting_id=meeting_id)
    return segments


def _evidence_quotes_are_verbatim(item, segments):
    by_id = {s.segment_id: s.text for s in segments}
    return all(eq.quote in by_id.get(eq.segment_id, "") or eq.quote == by_id.get(eq.segment_id) for eq in item.evidence_quotes)


def test_confirmed_commitment_fixture():
    segments = _load("confirmed_commitment.txt")
    items = extract_and_validate(segments, "m1")
    assert len(items) == 1
    item = items[0]
    assert item.classification == Classification.confirmed
    assert item.raw_owner_mention == "Rohit"
    assert item.raw_date_mention and "friday" in item.raw_date_mention.lower()
    assert len(item.evidence_quotes) >= 1
    assert _evidence_quotes_are_verbatim(item, segments)


def test_vague_suggestion_fixture_has_no_owner_and_is_not_confirmed():
    segments = _load("vague_suggestion.txt")
    items = extract_and_validate(segments, "m1")
    assert len(items) == 1
    item = items[0]
    assert item.classification == Classification.suggestion
    assert item.raw_owner_mention is None


def test_owner_reassignment_fixture_final_owner_is_the_new_person():
    segments = _load("owner_reassignment.txt")
    items = extract_and_validate(segments, "m1")
    assert len(items) == 1
    item = items[0]
    assert item.classification == Classification.confirmed
    assert item.raw_owner_mention == "Meera"


def test_deadline_change_fixture_final_date_is_the_corrected_one():
    segments = _load("deadline_change.txt")
    items = extract_and_validate(segments, "m1")
    assert len(items) == 1
    item = items[0]
    assert item.classification == Classification.confirmed
    assert item.raw_date_mention and "thursday" in item.raw_date_mention.lower()


def test_disagreement_fixture_is_disputed_not_confirmed():
    segments = _load("disagreement.txt")
    items = extract_and_validate(segments, "m1")
    assert len(items) == 1
    item = items[0]
    assert item.classification == Classification.disputed
    assert item.contradiction_note is not None


def test_cancelled_commitment_fixture_is_cancelled_not_confirmed():
    segments = _load("cancelled_commitment.txt")
    items = extract_and_validate(segments, "m1")
    assert len(items) == 1
    item = items[0]
    assert item.classification == Classification.cancelled
    assert item.contradiction_note is not None


def test_ambiguous_owner_fixture_extracts_confirmed_but_owner_mention_is_underspecified():
    # Classification is genuinely confirmed at the extraction/validation
    # layer -- the ambiguity is resolved (or rather, fails to resolve) one
    # layer up, in F007's owner resolver, not here.
    segments = _load("ambiguous_owner.txt")
    items = extract_and_validate(segments, "m1")
    assert len(items) == 1
    item = items[0]
    assert item.classification == Classification.confirmed
    assert item.raw_owner_mention == "Priya"


def test_prompt_injection_fixture_is_not_confirmed_and_injected_text_is_inert():
    segments = _load("prompt_injection.txt")
    items = extract_and_validate(segments, "m1")
    assert len(items) == 1
    item = items[0]
    # Rohit's reply is injected instruction text, not an affirmation --
    # it must not be classified as confirmed.
    assert item.classification != Classification.confirmed
    # The injected text is present only as inert evidence content, verbatim,
    # never interpreted as control flow.
    assert _evidence_quotes_are_verbatim(item, segments)


def test_code_switched_fixture_english_plus_telugu():
    segments = _load("code_switched.txt")
    items = extract_and_validate(segments, "m1")
    assert len(items) == 1
    item = items[0]
    assert item.classification == Classification.confirmed
    assert item.raw_owner_mention == "Priya"
    assert item.raw_date_mention and "monday" in item.raw_date_mention.lower()
    assert "share" in item.raw_text.lower()
    assert "deployment checklist" in item.raw_text.lower()
    assert _evidence_quotes_are_verbatim(item, segments)


def test_all_evidence_quotes_are_verbatim_substrings_across_every_fixture():
    for name in [
        "confirmed_commitment.txt", "vague_suggestion.txt", "owner_reassignment.txt",
        "deadline_change.txt", "disagreement.txt", "cancelled_commitment.txt",
        "ambiguous_owner.txt", "prompt_injection.txt", "code_switched.txt",
    ]:
        segments = _load(name)
        items = extract_and_validate(segments, "m1")
        for item in items:
            assert _evidence_quotes_are_verbatim(item, segments), f"{name}: non-verbatim evidence"
