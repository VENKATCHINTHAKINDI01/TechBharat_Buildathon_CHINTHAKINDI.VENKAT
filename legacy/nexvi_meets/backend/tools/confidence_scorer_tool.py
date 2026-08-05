"""
Combines the LLM's extraction confidence with the resolution outcomes
(owner match strength, whether the date resolved at all) into one
overall confidence score shown in the review UI. Low scores are what
should draw a reviewer's eye first -- this is display logic, not a
gate; nothing here blocks approval, it just ranks attention.
"""
from datetime import datetime


def compute_overall_confidence(
    extraction_confidence: float,
    owner_confidence: float | None,
    due_date_resolved: datetime | None,
    due_date_raw: str | None,
) -> float:
    weights = {"extraction": 0.5, "owner": 0.35, "date": 0.15}

    owner_component = owner_confidence if owner_confidence is not None else 0.0

    if due_date_raw is None:
        date_component = 1.0  # no date was claimed, nothing to fail
    else:
        date_component = 1.0 if due_date_resolved is not None else 0.0

    score = (
        extraction_confidence * weights["extraction"]
        + owner_component * weights["owner"]
        + date_component * weights["date"]
    )
    return round(min(max(score, 0.0), 1.0), 3)