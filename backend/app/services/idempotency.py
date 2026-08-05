"""F015: the idempotency key.

Absorbed from the legacy ``tools/dedupe_hash_tool.py`` with one deliberate
change: the key is computed from the **resolved owner participant id**,
not the raw spoken name. "Rohit", "rohit" and "Rohit Sharma" all resolve
to ``p-rohit`` (F007), so re-running the same meeting cannot produce two
issues just because the transcript spelled a name differently the second
time.

The key is stable across runs because every input is either deterministic
(meeting id, participant id) or normalized here (case, whitespace,
punctuation). It is stored with a unique index in Mongo, so the database
enforces the guarantee even if two approvals race.
"""
from __future__ import annotations

import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Deliberately
    aggressive: "Send the design doc." and "send the design doc" must
    produce the same key."""
    lowered = text.strip().lower()
    without_punct = _PUNCT_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", without_punct).strip()


def compute_dedupe_key(meeting_id: str, owner_participant_id: str | None, text: str) -> str:
    payload = f"{meeting_id}|{owner_participant_id or 'unassigned'}|{normalize_text(text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
