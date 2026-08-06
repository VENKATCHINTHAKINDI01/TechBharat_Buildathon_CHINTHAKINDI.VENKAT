"""Agent primitives.

An agent is a named unit of work that reads and writes one shared state
object and reaches the outside world **only** through the tool registry.
That constraint is what makes the system auditable: to know what an agent
can do, read its ``tools`` declaration, not its body.

The brief defines agentic as *"the system decides what actions are needed
and executes them through tools"*. Here that decision-making is explicit
and inspectable — routing conditions are named functions, every step is
timed and recorded, and the resulting ``AgentRun`` is persisted and shown
in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from app.core.config import Settings
from app.domain.models import (
    AgentStatus,
    AgentStep,
    GateDecision,
    MeetingRecord,
    Participant,
    ResolvedItem,
    TranscriptSegment,
    ValidatedItem,
)
from app.tools.registry import ToolRegistry


@dataclass
class PipelineState:
    """Shared state threaded through the agent graph.

    A dataclass rather than a dict so a typo is a type error, not a
    silently-missing key at 2am during a demo.
    """

    meeting_id: str
    filename: str
    content: str
    title: str
    meeting_date: date
    participants: list[Participant]

    utterances: list = field(default_factory=list)
    segments: list[TranscriptSegment] = field(default_factory=list)
    candidates: list[ValidatedItem] = field(default_factory=list)
    resolved: list[ResolvedItem] = field(default_factory=list)
    gate_decisions: dict[str, GateDecision] = field(default_factory=dict)
    record: Optional[MeetingRecord] = None
    carried_forward: list = field(default_factory=list)

    extractor_used: str = "unknown"
    normalizer_used: str = "none"
    fallback_reason: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def eligible_count(self) -> int:
        return sum(1 for d in self.gate_decisions.values() if d.eligible)


@dataclass
class AgentContext:
    """Everything an agent is allowed to touch."""

    tools: ToolRegistry
    repository: Any
    settings: Settings
    audit: Any
    extractor: Any = None
    fallback_extractor: Any = None
    normalizer: Any = None
    memory_store: Any = None


@runtime_checkable
class Agent(Protocol):
    name: str
    description: str
    tools: tuple[str, ...]

    async def run(self, state: PipelineState, ctx: AgentContext) -> PipelineState: ...


class AgentError(RuntimeError):
    """An agent failed in a way that should stop the run."""


async def execute(agent: Agent, state: PipelineState, ctx: AgentContext) -> tuple[PipelineState, AgentStep]:
    """Run one agent, timing it and capturing which tools it used.

    Failures are captured into an ``AgentStep`` rather than propagating,
    so a partially-failed run still produces a complete, honest trace —
    "graceful failure" means saying what broke, not pretending it didn't.
    """
    ctx.tools.reset_calls()
    started = datetime.now(timezone.utc)
    status = AgentStatus.ok
    error: Optional[str] = None
    summary = ""

    try:
        state = await agent.run(state, ctx)
        summary = getattr(state, "_last_summary", "") or ""
        if state.error:
            status = AgentStatus.failed
            error = state.error
    except Exception as exc:  # noqa: BLE001 - recorded, then surfaced in the trace
        status = AgentStatus.failed
        error = f"{type(exc).__name__}: {exc}"
        state.error = error

    finished = datetime.now(timezone.utc)
    step = AgentStep(
        agent=agent.name,
        status=status,
        started_at=started,
        finished_at=finished,
        duration_ms=max(0, int((finished - started).total_seconds() * 1000)),
        tools_used=ctx.tools.reset_calls(),
        summary=summary,
        error=error,
    )
    return state, step
