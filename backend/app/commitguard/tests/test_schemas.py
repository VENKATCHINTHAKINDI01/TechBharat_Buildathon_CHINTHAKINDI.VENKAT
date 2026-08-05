"""F004 acceptance tests -- see docs/acceptance-tests.md#f004."""
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.commitguard.models.schemas import (
    AuditEvent,
    AuditStage,
    CandidateItem,
    CandidateKind,
    Classification,
    DateResolutionMethod,
    EvidenceQuote,
    GateDecision,
    GitHubIssueRecord,
    OwnerResolutionMethod,
    Participant,
    ResolvedItem,
    ReviewDecision,
    ReviewDecisionValue,
    TranscriptSegment,
    ValidatedItem,
)


def test_transcript_segment_round_trip():
    seg = TranscriptSegment(segment_id="m1-000", speaker="Priya", start_ms=0, end_ms=1200, text="hello")
    dumped = seg.model_dump()
    assert TranscriptSegment.model_validate(dumped) == seg


def test_candidate_item_action_item_requires_evidence():
    with pytest.raises(ValidationError):
        CandidateItem(
            candidate_id="c1",
            meeting_id="m1",
            kind=CandidateKind.action_item,
            raw_text="do the thing",
            evidence_quotes=[],
            confidence=0.9,
        )


def test_candidate_item_with_evidence_round_trip():
    item = CandidateItem(
        candidate_id="c1",
        meeting_id="m1",
        kind=CandidateKind.action_item,
        raw_text="Priya will share the deployment checklist by Monday morning",
        evidence_quotes=[EvidenceQuote(segment_id="m1-000", quote="Priya, ... share chesthava?")],
        raw_owner_mention="Priya",
        raw_date_mention="Monday morning",
        confidence=0.87,
    )
    dumped = item.model_dump()
    assert CandidateItem.model_validate(dumped) == item


def test_candidate_item_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        CandidateItem(
            candidate_id="c1",
            meeting_id="m1",
            kind=CandidateKind.decision,
            raw_text="x",
            confidence=1.5,
        )


def test_validated_and_resolved_item_round_trip():
    resolved = ResolvedItem(
        candidate_id="c1",
        meeting_id="m1",
        kind=CandidateKind.action_item,
        raw_text="Priya will share the checklist",
        evidence_quotes=[EvidenceQuote(segment_id="m1-000", quote="share chesthava?")],
        confidence=0.9,
        classification=Classification.confirmed,
        owner_participant_id="p-priya",
        owner_resolution_method=OwnerResolutionMethod.exact_match,
        due_date=date(2026, 8, 10),
        date_resolution_method=DateResolutionMethod.relative,
    )
    dumped = resolved.model_dump()
    assert ResolvedItem.model_validate(dumped) == resolved
    # ValidatedItem is a strict subset -- a ResolvedItem must also validate as one
    assert ValidatedItem.model_validate(dumped)


def test_gate_decision_round_trip():
    gd = GateDecision(candidate_id="c1", eligible=False, reasons=["no owner resolved"], checked_at=datetime(2026, 8, 5, 12, 0, 0))
    assert GateDecision.model_validate(gd.model_dump()) == gd


def test_review_decision_requires_payload_when_approved():
    with pytest.raises(ValidationError):
        ReviewDecision(
            candidate_id="c1",
            reviewer="vyas",
            decision=ReviewDecisionValue.approved,
            final_payload=None,
            decided_at=datetime(2026, 8, 5, 12, 0, 0),
        )
    # rejected does not require a payload
    rd = ReviewDecision(
        candidate_id="c1",
        reviewer="vyas",
        decision=ReviewDecisionValue.rejected,
        final_payload=None,
        decided_at=datetime(2026, 8, 5, 12, 0, 0),
    )
    assert rd.final_payload is None


def test_audit_event_round_trip():
    ev = AuditEvent(
        event_id="e1",
        meeting_id="m1",
        candidate_id="c1",
        stage=AuditStage.gate,
        payload={"eligible": False},
        created_at=datetime(2026, 8, 5, 12, 0, 0),
    )
    assert AuditEvent.model_validate(ev.model_dump()) == ev


def test_github_issue_record_round_trip():
    rec = GitHubIssueRecord(
        dedupe_key="abc123",
        candidate_id="c1",
        github_issue_number=42,
        github_issue_url="https://github.com/org/repo/issues/42",
        created_at=datetime(2026, 8, 5, 12, 0, 0),
    )
    assert GitHubIssueRecord.model_validate(rec.model_dump()) == rec


def test_participant_round_trip():
    p = Participant(participant_id="p-priya", name="Priya", aliases=["Priya K"], email="priya@example.com")
    assert Participant.model_validate(p.model_dump()) == p


def test_missing_required_field_raises():
    with pytest.raises(ValidationError):
        TranscriptSegment(speaker="Priya", text="hi")  # missing segment_id
