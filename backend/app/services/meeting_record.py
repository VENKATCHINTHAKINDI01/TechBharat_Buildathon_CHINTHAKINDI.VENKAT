"""F011b: structured meeting record synthesis.

TechBharat brief, Use Case B: "Produce a structured meeting record
containing: an executive summary, the decisions made, open questions,
risks or blockers raised, and the action items."

Like F005/F006 (see reference_pipeline.py), the executive summary here is
a deterministic, templated reference implementation -- counts and a plain
listing of confirmed commitments -- not an LLM-generated narrative. It is
fully reproducible and requires no API key. Swapping in an LLM-generated
summary later only requires replacing ``_build_executive_summary``; the
partition logic (which item goes in which bucket) is deterministic by
design and should stay that way regardless of how the summary is worded.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import CandidateKind, Classification, MeetingRecord, ResolvedItem


def _build_executive_summary(
    decisions: list[ResolvedItem],
    open_questions: list[ResolvedItem],
    risks_blockers: list[ResolvedItem],
    action_items: list[ResolvedItem],
) -> str:
    confirmed_actions = [a for a in action_items if a.classification == Classification.confirmed]
    disputed_decisions = [d for d in decisions if d.classification == Classification.disputed]
    cancelled = [a for a in action_items if a.classification == Classification.cancelled]

    parts = [
        f"{len(action_items)} action item(s), {len(decisions)} decision(s), "
        f"{len(risks_blockers)} risk/blocker(s), {len(open_questions)} open question(s)."
    ]

    if confirmed_actions:
        commitments = "; ".join(
            f"{a.raw_owner_mention or 'unassigned'} will "
            f"{a.raw_text.split(' will ', 1)[-1] if ' will ' in a.raw_text else a.raw_text}"
            for a in confirmed_actions
        )
        parts.append(f"Confirmed commitments: {commitments}.")

    if disputed_decisions:
        parts.append(f"{len(disputed_decisions)} decision(s) remain disputed, no consensus reached.")

    if cancelled:
        parts.append(f"{len(cancelled)} item(s) were cancelled during the meeting.")

    return " ".join(parts)


def synthesize_meeting_record(meeting_id: str, resolved_items: list[ResolvedItem]) -> MeetingRecord:
    decisions = [i for i in resolved_items if i.kind == CandidateKind.decision]
    open_questions = [i for i in resolved_items if i.kind == CandidateKind.open_question]
    risks_blockers = [i for i in resolved_items if i.kind in (CandidateKind.risk, CandidateKind.blocker)]
    action_items = [i for i in resolved_items if i.kind == CandidateKind.action_item]

    return MeetingRecord(
        meeting_id=meeting_id,
        executive_summary=_build_executive_summary(decisions, open_questions, risks_blockers, action_items),
        decisions=decisions,
        open_questions=open_questions,
        risks_blockers=risks_blockers,
        action_items=action_items,
        generated_at=datetime.now(timezone.utc),
    )
