"""Assigning speakers to an uploaded recording, and re-analysing it.

A transcribed recording has no speaker labels — Whisper returns words,
not who said them — so every segment arrives as "Unknown speaker". That
is deliberate: owner resolution fails closed, so nothing from an untagged
recording can be approved. Guessing would manufacture the exact false
attribution the safety gate exists to prevent.

This module is how that gets undone by a human. The reviewer says who
spoke, and extraction runs again over the now-attributed transcript. A
line that read "Unknown speaker: Yes, I'll do it by Friday" becomes
"Rohit: Yes, I'll do it by Friday", and only then can the item name an
owner and pass the gate.

**Re-analysis refuses to run over decided work.** If any candidate in the
meeting has already been approved or rejected, re-extracting would either
orphan that decision or silently re-create work that was already actioned.
Both are worse than declining, so it declines and says which items are in
the way.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from app.core.config import Settings
from app.domain.models import Participant, TranscriptSegment
from app.domain.safety.gate import check_gate
from app.services.extraction.base import EvidenceReport, ExtractionError, drop_unsupported_evidence
from app.services.pipeline import build_extractor
from app.services.resolvers.combine import resolve_validated_items

logger = logging.getLogger("nexvi_meets.retagging")


class RetaggingError(RuntimeError):
    """Speaker assignment or re-analysis could not proceed."""


@dataclass
class RetagOutcome:
    segments_updated: int = 0
    candidates: list = field(default_factory=list)
    gate_decisions: dict = field(default_factory=dict)
    extractor_used: str = "unknown"
    fallback_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    reanalysed: bool = False


def apply_assignments(
    segments: list[dict],
    *,
    assignments: dict[str, str],
    relabel: dict[str, str],
    participants: list[Participant],
) -> tuple[list[dict], int]:
    """Rewrite speaker labels on stored segment dicts.

    Two forms, because both are genuinely useful:

    ``assignments`` maps one ``segment_id`` to one participant — for
    fixing a single line.

    ``relabel`` maps an existing speaker label to a participant — for the
    common case of "everything currently marked Unknown speaker was
    actually Arjun", which would otherwise be dozens of clicks.
    """
    name_by_id = {p.participant_id: p.name for p in participants}

    unknown = set(assignments.values()) | set(relabel.values())
    unknown -= set(name_by_id)
    if unknown:
        raise RetaggingError(
            "unknown participant id(s): " + ", ".join(sorted(unknown))
            + ". Speakers can only be set to someone in the participant list."
        )

    updated = 0
    result: list[dict] = []
    for segment in segments:
        current = dict(segment)
        target = assignments.get(current.get("segment_id", ""))
        if target is None:
            target = relabel.get(current.get("speaker", ""))
        if target is not None:
            new_name = name_by_id[target]
            if current.get("speaker") != new_name:
                current["speaker"] = new_name
                updated += 1
        result.append(current)

    return result, updated


async def reanalyse(
    *,
    repository,
    meeting_id: str,
    segments: list[dict],
    participants: list[Participant],
    meeting_date: date,
    settings: Settings,
) -> RetagOutcome:
    """Re-run extraction over a re-attributed transcript."""
    outcome = RetagOutcome(reanalysed=True)

    existing = await repository.list_items(meeting_id)
    decided = []
    for item in existing:
        decision = await repository.get_review_decision(item.candidate_id)
        if decision:
            decided.append(item.raw_text)
    if decided:
        raise RetaggingError(
            f"{len(decided)} item(s) in this meeting have already been reviewed, so "
            "re-analysis would orphan those decisions or duplicate work that was "
            "already created. Speakers were updated, but the commitments were left "
            "as they are. First reviewed item: " + repr(decided[0][:80])
        )

    typed = [TranscriptSegment.model_validate(s) for s in segments]
    primary, fallback = build_extractor(settings)
    outcome.extractor_used = getattr(primary, "name", "unknown")

    try:
        candidates = primary.extract(typed, meeting_id)
    except ExtractionError as exc:
        outcome.extractor_used = getattr(fallback, "name", "reference")
        outcome.fallback_reason = str(exc)
        outcome.warnings.append(
            f"The AI extractor failed, so Naina fell back to the pattern-based one. "
            f"Reason: {exc}"
        )
        logger.warning("re-analysis fell back: %s", exc)
        try:
            candidates = fallback.extract(typed, meeting_id)
        except ExtractionError as fallback_exc:
            outcome.warnings.append(f"Both extractors failed: {fallback_exc}")
            return outcome

    report = EvidenceReport()
    candidates = drop_unsupported_evidence(candidates, typed, report)
    if report.summary:
        outcome.warnings.append(f"Evidence check: {report.summary}")

    resolved = resolve_validated_items(candidates, participants, meeting_date)
    for item in resolved:
        outcome.gate_decisions[item.candidate_id] = check_gate(
            item, settings.confidence_threshold
        )

    # Clear first: re-extraction can produce a different number of items
    # with different ids, and leaving the old ones would show both runs
    # in the review queue.
    await repository.delete_items(meeting_id)
    await repository.save_items(resolved)
    outcome.candidates = resolved

    if not resolved:
        outcome.warnings.append(
            f"No commitments were found in {len(typed)} segments after re-analysis."
        )

    return outcome
