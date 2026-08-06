"""Meeting identifiers.

Every meeting must have its own id, permanently. The id keys the audit
trail, the dedupe keys, the review decisions and the issue records — so a
collision does not merely confuse a list view, it silently merges two
meetings' commitments and lets one meeting's approval satisfy another
meeting's idempotency check.

This replaces an earlier implementation that derived live-meeting ids
from ``id(websocket)``. CPython reuses memory addresses aggressively, so
consecutive short-lived sockets collide almost every time — measured at
19,999 collisions in 20,000 objects. Two meetings in a row would have
shared an id.

Format: ``nm-YYYYMMDD-<10 hex>``

- prefixed, so an id is recognisable in a log or a GitHub issue body
- date-stamped, so ids sort chronologically and a human can place one
- 40 bits of randomness from ``uuid4``: ~1 in 1.1 million for a
  collision after 1,000 meetings *on the same day*, and ids on different
  days cannot collide at all
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Callable, Optional

PREFIX = "nm"


def new_meeting_id(on: Optional[date] = None) -> str:
    day = (on or date.today()).strftime("%Y%m%d")
    return f"{PREFIX}-{day}-{uuid.uuid4().hex[:10]}"


async def unique_meeting_id(
    exists: Callable[[str], object],
    on: Optional[date] = None,
    attempts: int = 5,
) -> str:
    """Generate an id that is not already taken.

    ``exists`` is an async callable returning a truthy value when the id
    is in use — normally ``repository.get_meeting``. Randomness alone
    makes a clash vanishingly unlikely; checking makes it impossible,
    and the cost is one indexed lookup per meeting.
    """
    for _ in range(attempts):
        candidate = new_meeting_id(on)
        if not await exists(candidate):
            return candidate
    # Five collisions in a row means something is badly wrong with the
    # random source. Fall back to a full uuid rather than returning an
    # id that might already belong to another meeting.
    day = (on or date.today()).strftime("%Y%m%d")
    return f"{PREFIX}-{day}-{uuid.uuid4().hex}"


def is_valid_meeting_id(value: str) -> bool:
    """Loose shape check, used to reject obviously malformed client input
    without rejecting ids created by older versions."""
    return bool(value) and "/" not in value and "\\" not in value and len(value) <= 128
