"""F010 acceptance tests -- see docs/acceptance-tests.md#f010.

No LLM calls anywhere in this file: check_gate takes only structured,
already-resolved Pydantic data.
"""
import inspect
import itertools
from datetime import date, datetime

import pytest

from app.commitguard.models.schemas import (
    Classification,
    DateResolutionMethod,
    EvidenceQuote,
    OwnerResolutionMethod,
    ResolvedItem,
)
from app.commitguard.safety.gate import check_gate

THRESHOLD = 0.75


def _make_item(
    classification=Classification.confirmed,
    owner_resolved=True,
    evidence_present=True,
    contradiction_set=False,
    confidence_ok=True,
    date_resolved=True,
):
    return ResolvedItem(
        candidate_id="c1",
        meeting_id="m1",
        kind="decision",  # avoids the action_item-requires-evidence schema rule so evidence_present=False is constructible
        raw_text="Rohit will finish the migration",
        evidence_quotes=[EvidenceQuote(segment_id="m1-000", quote="I will finish it")] if evidence_present else [],
        confidence=0.9 if confidence_ok else 0.4,
        classification=classification,
        contradiction_of="c0" if contradiction_set else None,
        owner_participant_id="p-rohit" if owner_resolved else None,
        owner_resolution_method=OwnerResolutionMethod.exact_match if owner_resolved else OwnerResolutionMethod.unresolved,
        due_date=date(2026, 8, 7) if date_resolved else None,
        date_resolution_method=DateResolutionMethod.relative if date_resolved else DateResolutionMethod.unresolved,
    )


def _expected_eligible(classification, owner_resolved, evidence_present, contradiction_set, confidence_ok, date_resolved):
    if classification != Classification.confirmed:
        return False
    if not owner_resolved:
        return False
    if not evidence_present:
        return False
    if not confidence_ok:
        return False
    if not date_resolved:
        return False
    # contradiction_of set on an otherwise-confirmed item is resolved
    # lineage, not a blocking contradiction (see gate.py rule 3 docstring).
    return True


CLASSIFICATIONS = list(Classification)
BOOLS = [True, False]


@pytest.mark.parametrize(
    "classification,owner_resolved,evidence_present,contradiction_set,confidence_ok,date_resolved",
    list(itertools.product(CLASSIFICATIONS, BOOLS, BOOLS, BOOLS, BOOLS, BOOLS)),
)
def test_gate_truth_table_exhaustive(
    classification, owner_resolved, evidence_present, contradiction_set, confidence_ok, date_resolved
):
    item = _make_item(classification, owner_resolved, evidence_present, contradiction_set, confidence_ok, date_resolved)
    decision = check_gate(item, THRESHOLD)
    expected = _expected_eligible(
        classification, owner_resolved, evidence_present, contradiction_set, confidence_ok, date_resolved
    )
    assert decision.eligible == expected, (
        f"classification={classification} owner_resolved={owner_resolved} "
        f"evidence_present={evidence_present} contradiction_set={contradiction_set} "
        f"confidence_ok={confidence_ok} date_resolved={date_resolved} "
        f"-> got eligible={decision.eligible}, reasons={decision.reasons}"
    )
    if expected:
        assert decision.reasons == []
    else:
        assert decision.reasons != []


def test_rule_no_owner_blocks():
    item = _make_item(owner_resolved=False)
    decision = check_gate(item, THRESHOLD)
    assert not decision.eligible
    assert any("no owner" in r for r in decision.reasons)


def test_rule_low_confidence_blocks():
    item = _make_item(confidence_ok=False)
    decision = check_gate(item, THRESHOLD)
    assert not decision.eligible
    assert any("below threshold" in r for r in decision.reasons)


def test_rule_disputed_contradiction_blocks():
    item = _make_item(classification=Classification.disputed)
    decision = check_gate(item, THRESHOLD)
    assert not decision.eligible
    assert any("contradiction detected" in r for r in decision.reasons)


def test_rule_no_evidence_blocks():
    item = _make_item(evidence_present=False)
    decision = check_gate(item, THRESHOLD)
    assert not decision.eligible
    assert any("no transcript evidence" in r for r in decision.reasons)


def test_rule_rejected_blocks():
    item = _make_item(classification=Classification.rejected)
    decision = check_gate(item, THRESHOLD)
    assert not decision.eligible
    assert any("do not create" in r for r in decision.reasons)


def test_rule_cancelled_blocks():
    item = _make_item(classification=Classification.cancelled)
    decision = check_gate(item, THRESHOLD)
    assert not decision.eligible
    assert any("do not create" in r for r in decision.reasons)


def test_rule_unresolved_date_requires_edit():
    item = _make_item(date_resolved=False)
    decision = check_gate(item, THRESHOLD)
    assert not decision.eligible
    assert any("requires edit" in r for r in decision.reasons)


def test_fully_eligible_item_passes_clean():
    item = _make_item()
    decision = check_gate(item, THRESHOLD)
    assert decision.eligible
    assert decision.reasons == []


def test_gate_signature_cannot_receive_raw_transcript_text():
    """Structural guarantee against prompt injection: check_gate's only
    parameters are a ResolvedItem and a numeric threshold. There is no
    parameter through which raw transcript/LLM-output text could reach
    this function and influence its control flow."""
    sig = inspect.signature(check_gate)
    param_names = list(sig.parameters.keys())
    assert param_names == ["item", "confidence_threshold"]
    annotation = sig.parameters["item"].annotation
    annotation_name = annotation if isinstance(annotation, str) else annotation.__name__
    assert annotation_name == "ResolvedItem"


def test_checked_at_is_a_real_timestamp():
    item = _make_item()
    decision = check_gate(item, THRESHOLD)
    assert isinstance(decision.checked_at, datetime)
