"""End-to-end ingestion pipeline.

    transcript file
      -> parse (F002)            deterministic
      -> normalize (F003)        deterministic
      -> extract + validate      Groq if configured, deterministic fallback
      -> drop unsupported evidence   deterministic citation check
      -> resolve owner + date (F007, F008)  deterministic
      -> gate (F010)             deterministic
      -> meeting record (F011b)  deterministic
      -> persist + audit (F011)

Only one stage is non-deterministic, and its output is filtered by
deterministic code before anything downstream sees it. Every stage writes
an audit event, so the trail explains not just what was created but what
was considered and rejected.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from app.core.config import Settings, get_settings
from app.domain.models import (
    AuditStage,
    GateDecision,
    MeetingRecord,
    Participant,
    ResolvedItem,
)
from app.domain.safety.gate import check_gate
from app.services.audit import AuditLogger
from app.services.extraction.base import Extractor, ExtractionError, drop_unsupported_evidence
from app.services.extraction.reference import ReferenceExtractor
from app.services.ingestion.normalization import normalize
from app.services.ingestion.parser import TranscriptParseError, parse_transcript
from app.services.meeting_record import synthesize_meeting_record
from app.services.resolvers.combine import resolve_validated_items


@dataclass
class PipelineOutcome:
    meeting_id: str
    record: MeetingRecord
    items: list[ResolvedItem]
    gate_decisions: dict[str, GateDecision]
    extractor_used: str
    fallback_reason: str | None = None
    segments_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def eligible_count(self) -> int:
        return sum(1 for d in self.gate_decisions.values() if d.eligible)


def build_extractor(settings: Settings | None = None) -> tuple[Extractor, Extractor]:
    """Returns (primary, fallback).

    Groq is primary whenever a key is configured; the deterministic
    reference implementation is always the fallback so a provider outage
    degrades output quality instead of losing the meeting entirely.
    """
    settings = settings or get_settings()
    fallback = ReferenceExtractor()
    if settings.groq_enabled:
        from app.services.extraction.groq import GroqExtractor

        return GroqExtractor(settings), fallback
    return fallback, fallback


async def run_pipeline(
    *,
    repository,
    filename: str,
    content: str,
    title: str,
    meeting_date: date,
    participants: list[Participant],
    settings: Settings | None = None,
    extractor: Extractor | None = None,
    fallback_extractor: Extractor | None = None,
    meeting_id: str | None = None,
) -> PipelineOutcome:
    settings = settings or get_settings()
    meeting_id = meeting_id or uuid.uuid4().hex[:12]
    audit = AuditLogger(repository, meeting_id)
    warnings: list[str] = []

    # --- ingestion ---
    try:
        utterances = parse_transcript(filename, content)
    except TranscriptParseError as exc:
        await audit.record(AuditStage.ingestion, {"outcome": "parse_failed", "error": str(exc)})
        raise

    segments = normalize(utterances, meeting_id=meeting_id)
    await audit.record(
        AuditStage.ingestion,
        {
            "outcome": "parsed",
            "filename": filename,
            "segments": len(segments),
            "speakers": sorted({s.speaker for s in segments}),
        },
    )

    await repository.create_meeting(
        meeting_id=meeting_id,
        title=title,
        meeting_date=meeting_date.isoformat(),
        participants=participants,
    )

    # --- extraction + validation ---
    if extractor is None or fallback_extractor is None:
        primary, fallback = build_extractor(settings)
        extractor = extractor or primary
        fallback_extractor = fallback_extractor or fallback

    extractor_used = getattr(extractor, "name", "unknown")
    fallback_reason: str | None = None
    try:
        validated = extractor.extract(segments, meeting_id)
    except ExtractionError as exc:
        fallback_reason = str(exc)
        extractor_used = getattr(fallback_extractor, "name", "reference")
        warnings.append(f"Primary extractor failed, used fallback: {exc}")
        validated = fallback_extractor.extract(segments, meeting_id)

    before = len(validated)
    validated = drop_unsupported_evidence(validated, segments)
    dropped = before - len(validated)
    if dropped:
        warnings.append(f"{dropped} candidate(s) dropped for unsupported evidence quotes")

    await audit.record(
        AuditStage.extraction,
        {
            "extractor": extractor_used,
            "fallback_reason": fallback_reason,
            "candidates": len(validated),
            "dropped_for_unsupported_evidence": dropped,
        },
    )
    await audit.record(
        AuditStage.validation,
        {
            "classifications": {
                c: sum(1 for v in validated if v.classification.value == c)
                for c in sorted({v.classification.value for v in validated})
            }
        },
    )

    # --- resolution ---
    resolved = resolve_validated_items(validated, participants, meeting_date)
    await audit.record(
        AuditStage.resolution,
        {
            "owners_resolved": sum(1 for r in resolved if r.owner_participant_id),
            "owners_unresolved": sum(1 for r in resolved if not r.owner_participant_id),
            "dates_resolved": sum(1 for r in resolved if r.due_date),
            "dates_unresolved": sum(1 for r in resolved if not r.due_date),
        },
    )

    # --- gate ---
    gate_decisions: dict[str, GateDecision] = {}
    for item in resolved:
        decision = check_gate(item, settings.confidence_threshold)
        gate_decisions[item.candidate_id] = decision
        await audit.record(
            AuditStage.gate,
            {
                "eligible": decision.eligible,
                "reasons": decision.reasons,
                "context": "pipeline",
            },
            candidate_id=item.candidate_id,
        )

    # --- persist ---
    await repository.save_items(resolved)
    record = synthesize_meeting_record(meeting_id, resolved)
    await repository.save_meeting_record(record)

    return PipelineOutcome(
        meeting_id=meeting_id,
        record=record,
        items=resolved,
        gate_decisions=gate_decisions,
        extractor_used=extractor_used,
        fallback_reason=fallback_reason,
        segments_count=len(segments),
        warnings=warnings,
    )
