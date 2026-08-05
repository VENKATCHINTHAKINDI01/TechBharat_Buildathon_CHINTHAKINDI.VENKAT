"""Deterministic citation grading applied to every extractor's output.

This is the defense that makes an LLM extractor safe to trust with
evidence: it does not get to grade its own citations.
"""
from app.domain.models import (
    CandidateKind,
    Classification,
    EvidenceQuote,
    TranscriptSegment,
    ValidatedItem,
)
from app.services.extraction.base import drop_unsupported_evidence

SEGMENTS = [
    TranscriptSegment(segment_id="m1-000", speaker="Arjun", text="Rohit, can you finish the migration by Friday?"),
    TranscriptSegment(segment_id="m1-001", speaker="Rohit", text="Yes, I will finish the migration by Friday."),
]


def _item(quotes, kind=CandidateKind.action_item):
    return ValidatedItem(
        candidate_id="c1",
        meeting_id="m1",
        kind=kind,
        raw_text="Rohit will finish the migration",
        evidence_quotes=quotes,
        confidence=0.9,
        classification=Classification.confirmed,
    )


def test_verbatim_quote_survives():
    item = _item([EvidenceQuote(segment_id="m1-001", quote="I will finish the migration")])
    assert len(drop_unsupported_evidence([item], SEGMENTS)) == 1


def test_paraphrased_quote_is_dropped_and_takes_the_action_item_with_it():
    item = _item([EvidenceQuote(segment_id="m1-001", quote="Rohit agreed to do the migration")])
    assert drop_unsupported_evidence([item], SEGMENTS) == []


def test_quote_attributed_to_the_wrong_segment_is_dropped():
    item = _item([EvidenceQuote(segment_id="m1-000", quote="Yes, I will finish the migration")])
    assert drop_unsupported_evidence([item], SEGMENTS) == []


def test_quote_citing_a_nonexistent_segment_is_dropped():
    item = _item([EvidenceQuote(segment_id="m1-999", quote="anything")])
    assert drop_unsupported_evidence([item], SEGMENTS) == []


def test_mixed_quotes_keep_only_the_supported_one():
    item = _item(
        [
            EvidenceQuote(segment_id="m1-001", quote="I will finish the migration"),
            EvidenceQuote(segment_id="m1-001", quote="invented text"),
        ]
    )
    result = drop_unsupported_evidence([item], SEGMENTS)
    assert len(result) == 1
    assert len(result[0].evidence_quotes) == 1


def test_non_action_item_survives_without_evidence():
    """A decision with no usable citation is still worth showing a human;
    it just can never reach the gate as an action item."""
    item = _item([EvidenceQuote(segment_id="m1-000", quote="nope")], kind=CandidateKind.decision)
    result = drop_unsupported_evidence([item], SEGMENTS)
    assert len(result) == 1
    assert result[0].evidence_quotes == []
