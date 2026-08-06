"""The in-house agent orchestrator.

A small graph the project owns outright: named nodes, explicit edges,
conditional routing, and an interrupt point before human review. It has
no third-party runtime dependency, so it cannot break because an
orchestration library changed its API between minor versions — a failure
mode the archived LangGraph code explicitly warned about in its own
docstring.

The graph deliberately **stops** before any side effect. Human review is
a terminal state for the automated portion; resuming is a separate,
human-initiated call into ``app/services/approval.py``. An interrupt that
the system could resume on its own would not be a safety property.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from app.agents.base import Agent, AgentContext, PipelineState, execute
from app.domain.models import AgentRun, AgentStatus, AgentStep, AuditStage

# A routing condition inspects state and returns the name of the next
# agent, or None to continue in declared order. Named functions, not
# lambdas, so the trace and the docs can say why a branch was taken.
Router = Callable[[PipelineState], Optional[str]]

HUMAN_REVIEW = "human_review"


def stop_on_error(state: PipelineState) -> Optional[str]:
    """Route straight to the interrupt if a stage failed.

    The brief's "graceful failure" requirement: surface the failure to a
    human honestly rather than pushing a half-extracted meeting through
    resolution and the gate, where it would produce confident-looking
    garbage.
    """
    return HUMAN_REVIEW if state.error else None


def skip_when_nothing_extracted(state: PipelineState) -> Optional[str]:
    """No candidates is a legitimate outcome, not an error -- but there is
    nothing left to resolve or gate, so jump to the record agent."""
    if not state.candidates:
        return "record"
    return None


class AgentGraph:
    """Sequential agents with conditional routing and a terminal interrupt."""

    runtime = "inhouse"

    def __init__(
        self,
        agents: Iterable[Agent],
        routers: Optional[dict[str, Router]] = None,
        interrupt_before: str = HUMAN_REVIEW,
    ) -> None:
        self._agents: list[Agent] = list(agents)
        self._by_name = {a.name: a for a in self._agents}
        self._routers = routers or {}
        self.interrupt_before = interrupt_before

    @property
    def agent_names(self) -> list[str]:
        return [a.name for a in self._agents]

    def describe(self) -> list[dict]:
        return [
            {
                "name": a.name,
                "description": a.description,
                "tools": list(a.tools),
                "has_router": a.name in self._routers,
            }
            for a in self._agents
        ]

    async def run(self, state: PipelineState, ctx: AgentContext) -> tuple[PipelineState, AgentRun]:
        run = AgentRun(
            run_id=uuid.uuid4().hex[:12],
            meeting_id=state.meeting_id,
            runtime=self.runtime,
            started_at=datetime.now(timezone.utc),
        )

        index = 0
        visited: set[str] = set()
        while index < len(self._agents):
            agent = self._agents[index]

            # Guard against a router creating a cycle. A repeated agent is
            # a bug in routing, and a demo that hangs is worse than one
            # that reports a routing error.
            if agent.name in visited:
                state.error = f"routing cycle detected at agent '{agent.name}'"
                break
            visited.add(agent.name)

            state, step = await execute(agent, state, ctx)
            run.steps.append(step)
            await ctx.audit.record(
                AuditStage.agent_step,
                {
                    "agent": step.agent,
                    "status": step.status.value,
                    "duration_ms": step.duration_ms,
                    "tools_used": step.tools_used,
                    "summary": step.summary,
                    "error": step.error,
                },
            )

            if step.status == AgentStatus.failed:
                break

            router = self._routers.get(agent.name)
            target = router(state) if router else None
            if target == self.interrupt_before:
                break
            if target is not None:
                if target not in self._by_name:
                    state.error = f"router returned unknown agent '{target}'"
                    break
                index = self._agents.index(self._by_name[target])
                continue

            index += 1

        run.interrupted_at = self.interrupt_before
        run.finished_at = datetime.now(timezone.utc)
        run.steps.append(
            AgentStep(
                agent=self.interrupt_before,
                status=AgentStatus.interrupted,
                started_at=run.finished_at,
                finished_at=run.finished_at,
                duration_ms=0,
                summary=(
                    "Awaiting human approval. No external action can occur before a "
                    "person approves the exact payload."
                ),
            )
        )
        return state, run


def build_graph(agents: Optional[Iterable[Agent]] = None) -> AgentGraph:
    from app.agents.pipeline_agents import PIPELINE_AGENTS

    return AgentGraph(
        agents=agents if agents is not None else PIPELINE_AGENTS,
        routers={
            "ingestion": stop_on_error,
            "normalization": stop_on_error,
            "extraction": skip_when_nothing_extracted,
            "validation": skip_when_nothing_extracted,
            "resolution": stop_on_error,
        },
    )
