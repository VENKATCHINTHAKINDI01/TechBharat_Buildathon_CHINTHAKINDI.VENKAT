"""
Deterministic date resolution -- code, not LLM. Turns "by next Friday"
into an actual datetime, anchored to the meeting date. This is what
makes date resolution auditable and reproducible instead of a second
hallucination risk.
"""
from datetime import datetime
import dateparser


def resolve_due_date(due_date_raw: str | None, meeting_date: datetime) -> datetime | None:
    if not due_date_raw:
        return None
    resolved = dateparser.parse(
        due_date_raw,
        settings={
            "RELATIVE_BASE": meeting_date,
            "PREFER_DATES_FROM": "future",
        },
    )
    return resolved  # None if dateparser genuinely can't resolve it -- surfaced as unresolved in review UI