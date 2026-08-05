"""
Resolves an extracted owner name (e.g. "Priya") against the meeting's
attendee roster (pulled from the Google Calendar attendee list). This is
the fail-loud gate: below CONFIDENCE_THRESHOLD, we return None rather
than guess -- the review UI must flag this item for manual owner
assignment instead of silently picking the closest match.
"""
from rapidfuzz import fuzz, process

from app.models.meeting import Attendee
from app.models.action_item import OwnerResolution

CONFIDENCE_THRESHOLD = 80  # 0-100 rapidfuzz score; tune against real rosters


def resolve_owner(owner_raw: str, roster: list[Attendee]) -> OwnerResolution | None:
    if not roster or not owner_raw:
        return None

    names = [a.name for a in roster]
    match = process.extractOne(owner_raw, names, scorer=fuzz.token_sort_ratio)
    if match is None:
        return None

    matched_name, score, idx = match
    if score < CONFIDENCE_THRESHOLD:
        return None  # fail loud -- caller flags this item as needs_owner_review

    attendee = roster[idx]
    return OwnerResolution(
        name=attendee.name,
        email=attendee.email,
        confidence=round(score / 100, 3),
    )