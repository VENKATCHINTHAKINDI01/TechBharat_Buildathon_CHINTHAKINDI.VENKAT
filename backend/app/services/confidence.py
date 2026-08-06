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
) -> float:
    extraction = min(max(extraction_confidence, 0.0), 1.0)
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
