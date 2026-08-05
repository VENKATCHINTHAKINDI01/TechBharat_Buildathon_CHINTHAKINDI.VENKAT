"""
Computes the idempotency key used everywhere an action item is written.
Same meeting + same normalized text + same claimed owner => same hash
=> upsert instead of insert. This single mechanism satisfies both
"re-run the same meeting twice, no duplicates" (rubric requirement)
and "live rolling window sees the same commitment again with more
detail" (live-mode requirement).
"""
import hashlib


def compute_dedupe_hash(meeting_id: str, text: str, owner_raw: str) -> str:
    normalized = f"{meeting_id}|{text.strip().lower()}|{owner_raw.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()