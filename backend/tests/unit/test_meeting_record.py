"""F011b acceptance tests -- see docs/data-contracts.md#meetingrecord.

Runs the full chain -- ingestion -> extraction/validation -> owner/date
resolution -> meeting record synthesis -- over the fixture set, since
F011b is the first feature that actually wires the earlier ones together
end to end.
"""
from datetime import date
from pathlib import Path

from app.services.meeting_record import synthesize_meeting_record
from app.services.extraction.reference import extract_and_validate
from app.services.ingestion.normalization import normalize
from app.services.ingestion.parser import parse_txt
from app.domain.models import CandidateKind, Classification, Participant
from app.services.resolvers.combine import resolve_validated_item, resolve_validated_items

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
MEETING_DATE = date(2026, 8, 5)

PARTICIPANTS = [
    Participant(participant_id="p-rohit", name="Rohit"),
    Participant(participant_id="p-meera", name="Meera"),
    Participant(participant_id="p-priya", name="Priya"),
    Participant(participant_id="p-arjun", name="Arjun"),
]


def _pipeline(fixture_name: str):
    content = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    segments = normalize(parse_txt(content), meeting_id="m1")
    validated = extract_and_validate(segments, "m1")
    return resolve_validated_items(validated, PARTICIPANTS, MEETING_DATE)


def test_resolve_validated_item_carries_owner_and_date():
    resolved = _pipeline("confirmed_commitment.txt")
    item = resolved[0]
    assert item.owner_participant_id == "p-rohit"
    assert item.due_date == date(2026, 8, 7)
    assert item.classification == Classification.confirmed
    assert item.priority is not None  # F004b field survives resolution


def test_meeting_record_partitions_every_item_exactly_once():
    resolved = _pipeline("disagreement.txt")  # produces one 'decision' kind item
    record = synthesize_meeting_record("m1", resolved)
    all_bucketed = record.decisions + record.open_questions + record.risks_blockers + record.action_items
    assert len(all_bucketed) == len(resolved)
    assert {i.candidate_id for i in all_bucketed} == {i.candidate_id for i in resolved}
    assert len(record.decisions) == 1
    assert record.decisions[0].kind == CandidateKind.decision


def test_meeting_record_action_items_bucket():
    resolved = _pipeline("confirmed_commitment.txt")
    record = synthesize_meeting_record("m1", resolved)
    assert len(record.action_items) == 1
    assert record.decisions == []
    assert record.open_questions == []
    assert record.risks_blockers == []


def test_executive_summary_mentions_counts_and_confirmed_commitment():
    resolved = _pipeline("confirmed_commitment.txt")
    record = synthesize_meeting_record("m1", resolved)
    assert "1 action item(s)" in record.executive_summary
    assert "Confirmed commitments:" in record.executive_summary
    assert "Rohit" in record.executive_summary


def test_executive_summary_notes_disputed_decision():
    resolved = _pipeline("disagreement.txt")
    record = synthesize_meeting_record("m1", resolved)
    assert "disputed" in record.executive_summary.lower()


def test_executive_summary_notes_cancellation():
    resolved = _pipeline("cancelled_commitment.txt")
    record = synthesize_meeting_record("m1", resolved)
    assert "cancelled" in record.executive_summary.lower()


def test_meeting_record_round_trip():
    resolved = _pipeline("confirmed_commitment.txt")
    record = synthesize_meeting_record("m1", resolved)
    dumped = record.model_dump()
    from app.domain.models import MeetingRecord
    assert MeetingRecord.model_validate(dumped) == record


def test_empty_meeting_produces_empty_buckets_not_an_error():
    record = synthesize_meeting_record("empty-meeting", [])
    assert record.decisions == record.open_questions == record.risks_blockers == record.action_items == []
    assert "0 action item(s)" in record.executive_summary
