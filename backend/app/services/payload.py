"""Builds the exact GitHub issue payload a reviewer sees and approves.

Kept deterministic and separate from the tracker so that the payload
shown in the review UI, the payload written to the audit log, and the
payload actually sent are provably the same object.

Evidence is embedded in the issue body on purpose: the resulting GitHub
issue is self-justifying -- anyone reading it later can see the verbatim
transcript lines the commitment came from without opening Nexvi.Meets.
"""
from __future__ import annotations

from app.adapters.trackers.base import IssuePayload
from app.domain.models import Participant, ResolvedItem


def build_issue_payload(
    item: ResolvedItem,
    participants: list[Participant],
    meeting_title: str,
    github_login_by_participant: dict[str, str] | None = None,
) -> IssuePayload:
    by_id = {p.participant_id: p for p in participants}
    owner = by_id.get(item.owner_participant_id or "")
    owner_name = owner.name if owner else "unassigned"

    lines: list[str] = [item.raw_text, ""]
    lines.append(f"**Owner:** {owner_name}")
    if owner and owner.email:
        lines[-1] += f" <{owner.email}>"
    lines.append(f"**Due:** {item.due_date.isoformat() if item.due_date else 'unresolved'}")
    lines.append(f"**Priority:** {item.priority.value}")
    lines.append(f"**Confidence:** {item.confidence:.2f}")
    lines.append(f"**Classification:** {item.classification.value}")
    lines.append("")
    lines.append("### Transcript evidence")
    for quote in item.evidence_quotes:
        lines.append(f"> {quote.quote}")
        lines.append(f"> — `{quote.segment_id}`")
        lines.append("")
    lines.append("---")
    lines.append(
        f"Created by Nexvi.Meets from meeting *{meeting_title}* "
        f"(`{item.meeting_id}`, candidate `{item.candidate_id}`) after human approval."
    )

    labels = ["nexvi_meets", f"priority:{item.priority.value}"]

    assignees: list[str] = []
    if github_login_by_participant and item.owner_participant_id:
        login = github_login_by_participant.get(item.owner_participant_id)
        if login:
            assignees.append(login)

    return IssuePayload(
        title=item.raw_text if len(item.raw_text) <= 120 else item.raw_text[:117] + "...",
        body="\n".join(lines),
        labels=labels,
        assignees=assignees,
    )
