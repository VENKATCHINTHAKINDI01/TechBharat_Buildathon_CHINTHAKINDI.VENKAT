"""F004b acceptance tests -- see docs/data-contracts.md#f004b.

TechBharat Cohort #2 Buildathon brief, Use Case B, "Must-have
requirements": "Extract action items with an owner, a due date, a priority
and a confidence score." This file proves the field exists, defaults
sensibly, round-trips, and is derived deterministically by the reference
pipeline.
"""
from pathlib import Path

from app.commitguard.agents.reference_pipeline import extract_and_validate
from app.commitguard.ingestion.normalization import normalize
from app.commitguard.ingestion.parser import parse_txt
from app.commitguard.models.schemas import CandidateItem, CandidateKind, EvidenceQuote, Priority

FIXTURES = Path(__file__).resolve().parents[4] / "tests" / "fixtures"


def test_priority_defaults_to_medium():
    item = CandidateItem(
        candidate_id="c1",
        meeting_id="m1",
        kind=CandidateKind.decision,
        raw_text="x",
        confidence=0.8,
    )
    assert item.priority == Priority.medium


def test_priority_round_trips():
    item = CandidateItem(
        candidate_id="c1",
        meeting_id="m1",
        kind=CandidateKind.action_item,
        raw_text="x",
        evidence_quotes=[EvidenceQuote(segment_id="m1-000", quote="x")],
        priority=Priority.high,
        confidence=0.8,
    )
    assert CandidateItem.model_validate(item.model_dump()).priority == Priority.high


def test_confirmed_commitment_action_item_defaults_medium_priority():
    content = (FIXTURES / "confirmed_commitment.txt").read_text(encoding="utf-8")
    segments = normalize(parse_txt(content), meeting_id="m1")
    items = extract_and_validate(segments, "m1")
    assert items[0].priority == Priority.medium


def test_disputed_decision_gets_high_priority():
    content = (FIXTURES / "disagreement.txt").read_text(encoding="utf-8")
    segments = normalize(parse_txt(content), meeting_id="m1")
    items = extract_and_validate(segments, "m1")
    assert items[0].kind == CandidateKind.decision
    assert items[0].priority == Priority.high
