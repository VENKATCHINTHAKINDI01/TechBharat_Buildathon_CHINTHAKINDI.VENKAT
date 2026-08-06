"""Pipeline entry point — assembles the agent graph and runs it.

This module used to contain the pipeline logic inline. That logic now
lives in ``app/agents/``, one agent per stage, so the orchestration is
inspectable and each stage is independently testable. What remains here
is assembly: build the context (tools, extractors, adapters), pick a
runtime, run, persist the trace.

The graph always stops at the human-review interrupt. Nothing downstream
of it happens without a person, and that is enforced again at the tool
registry rather than trusted here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional
import uuid

from app.agents.base import AgentContext, PipelineState
from app.agents.langgraph_runtime import build_runtime
from app.core.config import Settings, get_settings
from app.domain.models import AgentRun, GateDecision, MeetingRecord, Participant, ResolvedItem
from app.services.audit import AuditLogger
from app.services.extraction.base import Extractor
from app.services.extraction.reference import ReferenceExtractor
from app.services.normalization import build_normalizer
from app.tools.catalog import build_registry


@dataclass
class PipelineOutcome:
    meeting_id: str
    record: Optional[MeetingRecord]
    items: list[ResolvedItem]
    gate_decisions: dict[str, GateDecision]
    extractor_used: str
    agent_run: AgentRun
    normalizer_used: str = "none"
    fallback_reason: Optional[str] = None
    segments_count: int = 0
    carried_forward: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def eligible_count(self) -> int:
        return sum(1 for d in self.gate_decisions.values() if d.eligible)


def build_extractor(settings: Settings | None = None) -> tuple[Extractor, Extractor]:
    """Returns (primary, fallback).

    Groq is primary whenever a key is configured; the deterministic
    reference implementation is always the fallback, so a provider outage
    degrades output quality instead of losing the meeting.
    """
    settings = settings or get_settings()
    fallback = ReferenceExtractor()
    if settings.groq_enabled:
        from app.services.extraction.groq import GroqExtractor

        return GroqExtractor(settings), fallback
    return fallback, fallback


def build_context(
    *,
    repository,
    settings: Settings,
    audit: AuditLogger,
    extractor: Extractor | None = None,
    fallback_extractor: Extractor | None = None,
    normalizer: Any = None,
    memory_store: Any = None,
) -> AgentContext:
    primary, fallback = build_extractor(settings)
    return AgentContext(
        tools=build_registry(),
        repository=repository,
        settings=settings,
        audit=audit,
        extractor=extractor or primary,
        fallback_extractor=fallback_extractor or fallback,
        normalizer=normalizer if normalizer is not None else build_normalizer(settings),
        memory_store=memory_store,
    )


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
    normalizer: Any = None,
    memory_store: Any = None,
    meeting_id: str | None = None,
) -> PipelineOutcome:
    settings = settings or get_settings()
    meeting_id = meeting_id or uuid.uuid4().hex[:12]
    audit = AuditLogger(repository, meeting_id)

    await repository.create_meeting(
        meeting_id=meeting_id,
        title=title,
        meeting_date=meeting_date.isoformat(),
        participants=participants,
    )

    ctx = build_context(
        repository=repository,
        settings=settings,
        audit=audit,
        extractor=extractor,
        fallback_extractor=fallback_extractor,
        normalizer=normalizer,
        memory_store=memory_store,
    )

    state = PipelineState(
        meeting_id=meeting_id,
        filename=filename,
        content=content,
        title=title,
        meeting_date=meeting_date,
        participants=participants,
    )

    graph = build_runtime(settings)
    state, run = await graph.run(state, ctx)
    await repository.save_agent_run(run)

    return PipelineOutcome(
        meeting_id=meeting_id,
        record=state.record,
        items=state.resolved,
        gate_decisions=state.gate_decisions,
        extractor_used=state.extractor_used,
        agent_run=run,
        normalizer_used=state.normalizer_used,
        fallback_reason=state.fallback_reason,
        segments_count=len(state.segments),
        carried_forward=state.carried_forward,
        warnings=state.warnings,
        error=state.error,
    )
