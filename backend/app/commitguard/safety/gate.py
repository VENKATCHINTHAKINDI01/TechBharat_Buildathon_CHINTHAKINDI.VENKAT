"""F010: the deterministic safety gate.

Non-negotiable product principle (AGENTS.md): the LLM may interpret the
meeting. Deterministic code decides whether an external action is allowed.
This module is that deterministic code, and it is the *only* place that
decision is made.

``check_gate`` takes only a ``ResolvedItem`` (a Pydantic model of already-
resolved, structured fields) and a confidence threshold -- never a raw
transcript string, never an LLM response, never anything that could carry
an embedded instruction. This is a structural guarantee, not just a
convention: there is no parameter through which free-text transcript
content could reach this function and influence its control flow (see the
prompt_injection fixture test in test_extraction_validation.py, and
test_gate.py::test_gate_signature_cannot_receive_raw_transcript_text below).

Six rules, all deterministic, all independently evaluated so ``reasons``
is exhaustive rather than short-circuited on the first failure:

1. No owner resolved                    -> cannot auto-approve.
2. Confidence below threshold           -> manual review required.
3. Contradiction detected (unresolved)  -> block creation.
4. No transcript evidence               -> block creation.
5. Rejected or cancelled classification -> do not create.
6. Relative date unresolved             -> require edit before approval.

``eligible`` is True only if every rule passes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.commitguard.models.schemas import Classification, GateDecision, ResolvedItem


def check_gate(item: ResolvedItem, confidence_threshold: float) -> GateDecision:
    reasons: list[str] = []

    # Rule 1: no owner -> cannot auto-approve.
    if item.owner_participant_id is None:
        reasons.append("no owner resolved: cannot auto-approve")

    # Rule 2: confidence below threshold -> manual review.
    if item.confidence < confidence_threshold:
        reasons.append(
            f"confidence {item.confidence:.2f} below threshold {confidence_threshold:.2f}: manual review required"
        )

    # Rule 3: contradiction detected -> block creation.
    # A 'disputed' classification is itself an unresolved contradiction.
    # A non-null contradiction_of on anything other than a 'confirmed' item
    # means the supersession/cancellation hasn't landed on a clean final
    # state -- block until it does. (On a 'confirmed' item, contradiction_of
    # is descriptive lineage for an already-resolved correction and does not
    # block by itself.)
    if item.classification == Classification.disputed:
        reasons.append("contradiction detected: item is disputed, no consensus reached")
    elif item.contradiction_of is not None and item.classification != Classification.confirmed:
        reasons.append("contradiction detected: unresolved supersession/cancellation")

    # Rule 4: no transcript evidence -> block creation.
    if not item.evidence_quotes:
        reasons.append("no transcript evidence: block creation")

    # Rule 5: rejected or cancelled -> do not create.
    if item.classification in (Classification.rejected, Classification.cancelled):
        reasons.append(f"classification is '{item.classification.value}': do not create")

    # Rule 6: relative date unresolved -> require edit.
    if item.due_date is None:
        reasons.append("date unresolved: requires edit before approval")

    # Not one of the six enumerated rules, but implied by the mission
    # statement and by GateDecision's own contract in data-contracts.md:
    # only a genuinely confirmed commitment is eligible at all.
    if item.classification != Classification.confirmed:
        msg = f"classification is '{item.classification.value}', not 'confirmed'"
        if msg not in reasons and not any("classification is" in r for r in reasons):
            reasons.append(msg)

    eligible = len(reasons) == 0

    return GateDecision(
        candidate_id=item.candidate_id,
        eligible=eligible,
        reasons=reasons,
        checked_at=datetime.now(timezone.utc),
    )
