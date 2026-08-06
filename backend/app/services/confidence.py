"""Composite confidence scoring (restored from the archived tree).

The model reports how sure it is that a sentence was a commitment. That
is only one of three things that can be wrong. This blends it with the
two deterministic resolution outcomes:

    extraction  0.50  the model's own certainty
    owner       0.35  did the name resolve to exactly one real person
    date        0.15  did the spoken deadline resolve to a real date

Unlike the legacy version, this is **not** display-only ranking: the
blended score is what the safety gate compares against the threshold. An
item the model was confident about but whose owner could not be resolved
now scores low *and* is blocked by the owner rule — belt and braces, in
the same direction.

A date that was never spoken is not a failure (nothing was claimed), so
it scores full marks on that component; the gate blocks it separately via
the unresolved-date rule.
"""
from __future__ import annotations

from app.domain.models import DateResolutionMethod, OwnerResolutionMethod

WEIGHTS = {"extraction": 0.50, "owner": 0.35, "date": 0.15}

# How much to trust each owner-resolution path.
_OWNER_COMPONENT = {
    OwnerResolutionMethod.exact_match: 1.0,
    OwnerResolutionMethod.fuzzy_match: 0.8,
    OwnerResolutionMethod.unresolved: 0.0,
}


def compute_confidence(
    *,
    extraction_confidence: float,
    owner_method: OwnerResolutionMethod,
    date_method: DateResolutionMethod,
    date_was_claimed: bool,
    human_confirmed: bool = False,
) -> float:
    """
    ``human_confirmed`` replaces the extraction component outright.

    Without this the system had a dead end: a reviewer could correct a
    vague item's classification, owner AND date, and the model's original
    low score would still hold it under the threshold. Someone who was in
    the room knows better than the extractor did, and refusing to let them
    say so is not caution -- it is just being unhelpful.
    """
    extraction = 1.0 if human_confirmed else min(max(extraction_confidence, 0.0), 1.0)
    owner = _OWNER_COMPONENT.get(owner_method, 0.0)

    if not date_was_claimed:
        date = 1.0  # nothing claimed, nothing to get wrong
    else:
        date = 1.0 if date_method != DateResolutionMethod.unresolved else 0.0

    score = (
        extraction * WEIGHTS["extraction"]
        + owner * WEIGHTS["owner"]
        + date * WEIGHTS["date"]
    )
    return round(min(max(score, 0.0), 1.0), 3)


# ---------------------------------------------------------------------------
# Per-field confidence
# ---------------------------------------------------------------------------


def compute_field_confidence(
    *,
    extraction_confidence: float,
    owner_method: OwnerResolutionMethod,
    date_method: DateResolutionMethod,
    date_was_claimed: bool,
    state_settled: bool,
    human_confirmed: bool = False,
) -> "FieldConfidence":
    """Score each field separately.

    A single blended number tells a reviewer something is wrong but not
    what to fix. Splitting it lets the gate say "the owner is the weak
    part", which is the difference between an actionable message and a
    shrug.

    ``state`` scores how settled the commitment is: a thread still sitting
    at `proposed` or `reassigned` is genuinely less certain than one where
    the owner has said yes to the current terms, and that is information
    the blend was previously throwing away.
    """
    from app.domain.commitment import FieldConfidence

    text = 1.0 if human_confirmed else min(max(extraction_confidence, 0.0), 1.0)

    owner = {
        OwnerResolutionMethod.exact_match: 1.0,
        OwnerResolutionMethod.fuzzy_match: 0.8,
        OwnerResolutionMethod.unresolved: 0.0,
    }.get(owner_method, 0.0)

    if not date_was_claimed:
        date = 1.0  # nothing claimed, nothing to get wrong
    else:
        date = 1.0 if date_method != DateResolutionMethod.unresolved else 0.0

    state = 1.0 if (state_settled or human_confirmed) else 0.4

    return FieldConfidence(
        text=round(text, 3), owner=round(owner, 3), date=round(date, 3), state=round(state, 3)
    )
