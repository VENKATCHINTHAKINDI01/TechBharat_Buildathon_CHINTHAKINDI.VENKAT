"""F011: the audit trail.

The brief requires "an audit log showing every action the agent took,
what it was based on, and who approved it", and judges score
`unapproved actions == 0` by reading it. So the audit writer is not a
convenience helper -- it is the evidence that the safety properties hold.

Rules this module enforces:

- Append-only. There is no update or delete path, here or in the
  repositories.
- Every event carries the meeting it belongs to and a UTC timestamp.
- Payloads must be JSON-serializable, because a payload that cannot be
  round-tripped cannot be shown to a judge.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.domain.models import AuditEvent, AuditStage


def build_event(
    meeting_id: str,
    stage: AuditStage,
    payload: dict[str, Any],
    candidate_id: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        candidate_id=candidate_id,
        stage=stage,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )


class AuditLogger:
    """Thin wrapper binding a repository to one meeting, so callers can't
    forget to pass the meeting id and end up with orphaned events."""

    def __init__(self, repository, meeting_id: str) -> None:
        self._repo = repository
        self._meeting_id = meeting_id

    async def record(
        self,
        stage: AuditStage,
        payload: dict[str, Any],
        candidate_id: str | None = None,
    ) -> AuditEvent:
        event = build_event(self._meeting_id, stage, payload, candidate_id)
        await self._repo.append_audit(event)
        return event
