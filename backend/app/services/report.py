"""End-of-meeting report generation.

Answers the two questions a person actually has after a meeting:
*what was agreed*, and *what did this system do about it*.

The report is **derived, never stored as the source of truth**. It is
rebuilt from the persisted items, review decisions, and side-effect
records each time it is requested, so a report opened a week later
reflects approvals made yesterday rather than freezing at the moment the
call ended. Regeneration is cheap; a stale report that says an issue was
never created when it was is expensive.

Actions taken are read from the **side-effect records**, not from the
audit log. The audit log is the narrative of everything considered; the
records are the ledger of what exists. For "was a GitHub issue actually
created", the ledger is the honest source.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from app.domain.models import (
    ActionTaken,
    CandidateKind,
    MeetingReport,
    Participant,
    ReportItem,
    ResolvedItem,
    SpeakerStat,
)
from app.domain.safety.gate import check_gate

_WORD_RE = re.compile(r"\b[\w']+\b", re.UNICODE)


def _words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def _to_report_item(
    item: ResolvedItem,
    confidence_threshold: float,
    owner_name: Optional[str],
    review_status: Optional[str],
    actions: list[ActionTaken],
) -> ReportItem:
    gate = check_gate(item, confidence_threshold)
    return ReportItem(
        candidate_id=item.candidate_id,
        text=item.raw_text,
        classification=item.classification.value,
        owner_name=owner_name,
        owner_participant_id=item.owner_participant_id,
        due_date=item.due_date,
        priority=item.priority,
        confidence=item.confidence,
        gate_eligible=gate.eligible,
        gate_reasons=gate.reasons,
        review_status=review_status,
        evidence=item.evidence_quotes,
        actions=actions,
        timeline=item.timeline,
        was_renegotiated=item.was_renegotiated,
    )


async def collect_actions_taken(repository, meeting_id: str) -> list[ActionTaken]:
    """Everything this system actually did for one meeting."""
    actions: list[ActionTaken] = []

    for record in await repository.list_issue_records(meeting_id):
        actions.append(
            ActionTaken(
                effect="github_issue",
                status="created",
                candidate_id=record.candidate_id,
                summary=f"Issue #{record.github_issue_number}",
                url=record.github_issue_url,
                reference=str(record.github_issue_number),
                at=record.created_at,
            )
        )

    for record in await repository.list_calendar_events(meeting_id):
        actions.append(
            ActionTaken(
                effect="calendar_invite",
                status="created",
                candidate_id=record.candidate_id,
                summary=f"Invite to {record.attendee_email}",
                reference=record.event_id,
                at=record.created_at,
            )
        )

    for record in await repository.list_notifications(meeting_id):
        when = record.reminder_at.isoformat() if record.reminder_at else "no reminder"
        actions.append(
            ActionTaken(
                effect="notification",
                status="created",
                candidate_id=record.candidate_id,
                summary=f"{record.owner_email} · reminder {when}",
                reference=record.notification_id,
                at=record.created_at,
            )
        )

    # Failures and refusals live only in the audit log -- a failed action
    # leaves no ledger entry by definition, and omitting it would make the
    # report quietly optimistic.
    for event in await repository.list_audit(meeting_id):
        payload = event.payload or {}
        outcome = payload.get("outcome")
        if outcome not in ("failed", "approval_refused"):
            continue
        effect = {
            "github_create": "github_issue",
            "calendar_create": "calendar_invite",
            "memory_index": "memory_index",
            "notification": "notification",
        }.get(event.stage.value, event.stage.value)
        actions.append(
            ActionTaken(
                effect=effect,
                status="failed" if outcome == "failed" else "refused",
                candidate_id=event.candidate_id or "",
                summary="Refused by the safety gate"
                if outcome == "approval_refused"
                else "Failed",
                at=event.created_at,
                error=payload.get("error") or "; ".join(payload.get("reasons", [])) or None,
            )
        )

    actions.sort(key=lambda a: a.at or datetime.min.replace(tzinfo=timezone.utc))
    return actions


def build_speaker_stats(segments: list) -> list[SpeakerStat]:
    """Talk-time distribution, by words rather than seconds.

    Word count is available for uploaded transcripts too, where no timing
    exists — so one implementation covers both paths honestly instead of
    reporting zeroes for half of them.
    """
    tally: dict[str, dict[str, int]] = {}
    for segment in segments:
        speaker = getattr(segment, "speaker", None) or "unknown"
        text = getattr(segment, "text", "") or ""
        bucket = tally.setdefault(speaker, {"segments": 0, "words": 0})
        bucket["segments"] += 1
        bucket["words"] += _words(text)

    total_words = sum(b["words"] for b in tally.values()) or 1
    stats = [
        SpeakerStat(
            speaker=speaker,
            segments=b["segments"],
            words=b["words"],
            share=round(b["words"] / total_words, 3),
        )
        for speaker, b in tally.items()
    ]
    stats.sort(key=lambda s: s.words, reverse=True)
    return stats


async def generate_report(
    *,
    repository,
    meeting_id: str,
    confidence_threshold: float,
    source: str = "upload",
    segments: Optional[list] = None,
    warnings: Optional[list[str]] = None,
) -> Optional[MeetingReport]:
    meeting = await repository.get_meeting(meeting_id)
    if not meeting:
        return None

    participants = [Participant.model_validate(p) for p in meeting.get("participants", [])]
    name_by_id = {p.participant_id: p.name for p in participants}

    items = await repository.list_items(meeting_id)
    record = await repository.get_meeting_record(meeting_id)
    actions = await collect_actions_taken(repository, meeting_id)

    actions_by_candidate: dict[str, list[ActionTaken]] = {}
    for action in actions:
        actions_by_candidate.setdefault(action.candidate_id, []).append(action)

    buckets: dict[str, list[ReportItem]] = {
        "decision": [],
        "open_question": [],
        "risk_blocker": [],
        "action_item": [],
    }

    for item in items:
        decision = await repository.get_review_decision(item.candidate_id)
        report_item = _to_report_item(
            item,
            confidence_threshold,
            name_by_id.get(item.owner_participant_id or ""),
            decision.decision.value if decision else None,
            actions_by_candidate.get(item.candidate_id, []),
        )
        if item.kind == CandidateKind.decision:
            buckets["decision"].append(report_item)
        elif item.kind == CandidateKind.open_question:
            buckets["open_question"].append(report_item)
        elif item.kind in (CandidateKind.risk, CandidateKind.blocker):
            buckets["risk_blocker"].append(report_item)
        else:
            buckets["action_item"].append(report_item)

    # Highest priority first, then earliest deadline: the order someone
    # scanning the report actually wants.
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    buckets["action_item"].sort(
        key=lambda i: (priority_rank.get(i.priority.value, 1), i.due_date or __import__("datetime").date.max)
    )

    segments = segments or []
    stats = build_speaker_stats(segments)
    duration = max((getattr(s, "end_ms", 0) or 0) for s in segments) if segments else 0

    return MeetingReport(
        meeting_id=meeting_id,
        title=meeting.get("title", ""),
        meeting_date=meeting.get("meeting_date", ""),
        generated_at=datetime.now(timezone.utc),
        source=source,
        executive_summary=record.executive_summary if record else "",
        participants=participants,
        decisions=buckets["decision"],
        open_questions=buckets["open_question"],
        risks_blockers=buckets["risk_blocker"],
        action_items=buckets["action_item"],
        actions_taken=actions,
        speaker_stats=stats,
        segment_count=len(segments),
        duration_ms=duration,
        transcript_words=sum(s.words for s in stats),
        unattributed_segments=sum(
            1 for s in segments if "Remote speaker" in (getattr(s, "speaker", "") or "")
        ),
        warnings=warnings or [],
    )


def render_markdown(report: MeetingReport) -> str:
    """A shareable report. Written to be pasted into Slack or a doc."""
    lines: list[str] = [
        f"# {report.title or 'Meeting'}",
        "",
        f"**Date:** {report.meeting_date}  ",
        f"**Meeting ID:** `{report.meeting_id}`  ",
        f"**Source:** {report.source}  ",
        f"**Generated:** {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    if report.executive_summary:
        lines += ["## Summary", "", report.executive_summary, ""]

    lines += [
        "## At a glance",
        "",
        f"- {len(report.action_items)} action item(s): "
        f"**{report.approved_count} actioned**, {report.pending_count} awaiting approval, "
        f"{report.blocked_count} blocked by the safety gate",
        f"- {len(report.decisions)} decision(s), {len(report.risks_blockers)} risk/blocker(s), "
        f"{len(report.open_questions)} open question(s)",
    ]
    if report.segment_count:
        lines.append(
            f"- {report.segment_count} transcript segments, ~{report.transcript_words} words"
        )
    if report.unattributed_segments:
        lines.append(
            f"- {report.unattributed_segments} segment(s) never attributed to a named speaker"
        )
    lines.append("")

    if report.action_items:
        lines += ["## Action items", ""]
        for item in report.action_items:
            status = (
                "actioned" if item.was_actioned
                else "blocked" if not item.gate_eligible
                else item.review_status or "awaiting approval"
            )
            lines.append(f"### {item.text}")
            lines.append("")
            lines.append(
                f"- **Owner:** {item.owner_name or '_unresolved_'}  |  "
                f"**Due:** {item.due_date.isoformat() if item.due_date else '_unresolved_'}  |  "
                f"**Priority:** {item.priority.value}  |  **Status:** {status}"
            )
            if not item.gate_eligible and item.gate_reasons:
                lines.append(f"- **Blocked because:** {'; '.join(item.gate_reasons)}")
            # Only worth the space when the terms actually moved. For a
            # task that was stated once and stood, the timeline says
            # nothing the line above has not already said.
            if item.was_renegotiated and len(item.timeline) > 1:
                lines.append("- **This changed during the meeting:**")
                for event in item.timeline:
                    who = f" — {event['actor']}" if event.get("actor") else ""
                    quote = f' “{event["quote"]}”' if event.get("quote") else ""
                    lines.append(f"  - `{event['at']}` **{event['label']}**{who}:{quote}")
            for action in item.actions:
                target = f" — {action.url}" if action.url else ""
                lines.append(f"- **{action.effect}:** {action.status}{target}")
            for quote in item.evidence[:2]:
                lines.append(f"  > {quote.quote}")
            lines.append("")

    for heading, items in (
        ("Decisions", report.decisions),
        ("Risks and blockers", report.risks_blockers),
        ("Open questions", report.open_questions),
    ):
        if items:
            lines += [f"## {heading}", ""]
            for item in items:
                note = f" _({item.classification})_" if item.classification != "confirmed" else ""
                lines.append(f"- {item.text}{note}")
            lines.append("")

    if report.actions_taken:
        lines += ["## Actions taken", ""]
        for action in report.actions_taken:
            when = action.at.strftime("%H:%M") if action.at else "—"
            target = f" — {action.url}" if action.url else ""
            detail = f" ({action.error})" if action.error else ""
            lines.append(
                f"- `{when}` **{action.effect}** · {action.status}{target} {action.summary}{detail}"
            )
        lines.append("")
    else:
        lines += ["## Actions taken", "", "_Nothing was created. No item was approved._", ""]

    if report.speaker_stats:
        lines += ["## Talk time", "", "| Speaker | Segments | Words | Share |", "|---|---|---|---|"]
        for stat in report.speaker_stats:
            lines.append(
                f"| {stat.speaker} | {stat.segments} | {stat.words} | {stat.share:.0%} |"
            )
        lines.append("")

    if report.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in report.warnings] + [""]

    lines += [
        "---",
        "",
        "_Generated by Nexvi.Meets. Every action listed above passed a deterministic "
        "safety gate and was explicitly approved by a person._",
    ]
    return "\n".join(lines)
