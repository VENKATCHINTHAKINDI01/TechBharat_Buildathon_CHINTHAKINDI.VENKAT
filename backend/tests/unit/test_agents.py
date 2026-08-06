"""Agent graph behaviour: ordering, routing, tracing, and the interrupt."""
from datetime import date

import pytest

from app.adapters.repositories.memory import InMemoryRepository
from app.agents.base import AgentContext, PipelineState
from app.agents.orchestrator import HUMAN_REVIEW, AgentGraph, build_graph
from app.core.config import Settings
from app.domain.models import AgentStatus, Participant
from app.services.audit import AuditLogger
from app.services.extraction.reference import ReferenceExtractor
from app.services.normalization import NullNormalizer
from app.tools.catalog import build_registry
from tests.conftest import MEETING_DATE, load_fixture

PARTICIPANTS = [
    Participant(participant_id="p-arjun", name="Arjun"),
    Participant(participant_id="p-rohit", name="Rohit"),
]


def _ctx(repository=None, memory_store=None) -> AgentContext:
    repository = repository or InMemoryRepository()
    return AgentContext(
        tools=build_registry(),
        repository=repository,
        settings=Settings(confidence_threshold=0.75),
        audit=AuditLogger(repository, "m1"),
        extractor=ReferenceExtractor(),
        fallback_extractor=ReferenceExtractor(),
        normalizer=NullNormalizer(),
        memory_store=memory_store,
    )


def _state(fixture="confirmed_commitment.txt") -> PipelineState:
    return PipelineState(
        meeting_id="m1",
        filename=fixture,
        content=load_fixture(fixture),
        title="Standup",
        meeting_date=MEETING_DATE,
        participants=PARTICIPANTS,
    )


async def test_graph_runs_all_agents_in_order():
    state, run = await build_graph().run(_state(), _ctx())
    assert [s.agent for s in run.steps] == [
        "ingestion", "normalization", "extraction", "validation",
        "resolution", "gate", "record", HUMAN_REVIEW,
    ]
    assert state.error is None


async def test_run_always_ends_at_the_human_review_interrupt():
    """The automated portion is terminal. Nothing resumes itself."""
    _, run = await build_graph().run(_state(), _ctx())
    assert run.interrupted_at == HUMAN_REVIEW
    assert run.steps[-1].agent == HUMAN_REVIEW
    assert run.steps[-1].status == AgentStatus.interrupted


async def test_every_step_is_timed_and_records_its_tools():
    _, run = await build_graph().run(_state(), _ctx())
    ingestion = next(s for s in run.steps if s.agent == "ingestion")
    assert ingestion.tools_used == ["parse_transcript"]
    assert ingestion.duration_ms >= 0
    resolution = next(s for s in run.steps if s.agent == "resolution")
    assert resolution.tools_used == ["resolve_items"]


async def test_pipeline_produces_a_gated_eligible_candidate():
    state, _ = await build_graph().run(_state(), _ctx())
    assert len(state.resolved) == 1
    assert state.eligible_count == 1
    assert state.record is not None


async def test_a_failing_agent_stops_the_run_and_is_recorded():
    class Exploding:
        name = "extraction"
        description = "always fails"
        tools = ()

        async def run(self, state, ctx):
            raise RuntimeError("provider on fire")

    from app.agents.pipeline_agents import IngestionAgent, NormalizationAgent

    graph = AgentGraph([IngestionAgent(), NormalizationAgent(), Exploding()])
    state, run = await graph.run(_state(), _ctx())

    failed = next(s for s in run.steps if s.agent == "extraction")
    assert failed.status == AgentStatus.failed
    assert "provider on fire" in failed.error
    assert state.error is not None
    # It still reached the interrupt rather than hanging.
    assert run.steps[-1].agent == HUMAN_REVIEW


async def test_router_can_skip_ahead_when_nothing_was_extracted():
    from app.agents.orchestrator import skip_when_nothing_extracted

    empty = _state()
    empty.candidates = []
    assert skip_when_nothing_extracted(empty) == "record"

    empty.candidates = ["something"]
    assert skip_when_nothing_extracted(empty) is None


async def test_router_diverts_to_the_interrupt_on_error():
    from app.agents.orchestrator import stop_on_error

    state = _state()
    assert stop_on_error(state) is None
    state.error = "boom"
    assert stop_on_error(state) == HUMAN_REVIEW


async def test_routing_cycle_is_detected_rather_than_hanging():
    from app.agents.pipeline_agents import IngestionAgent, NormalizationAgent

    graph = AgentGraph(
        [IngestionAgent(), NormalizationAgent()],
        routers={"normalization": lambda s: "ingestion"},
    )
    state, _ = await graph.run(_state(), _ctx())
    assert "cycle" in (state.error or "")


async def test_agent_run_is_persisted_with_the_meeting():
    repository = InMemoryRepository()
    ctx = _ctx(repository)
    _, run = await build_graph().run(_state(), ctx)
    await repository.save_agent_run(run)
    assert (await repository.get_agent_run("m1")).run_id == run.run_id


async def test_graph_describes_its_agents_and_their_tools():
    described = build_graph().describe()
    names = [d["name"] for d in described]
    assert "gate" in names
    gate = next(d for d in described if d["name"] == "gate")
    assert gate["tools"] == ["safety_gate"]
    assert all(d["description"] for d in described)


async def test_code_switched_meeting_runs_through_the_graph():
    state, _ = await build_graph().run(
        PipelineState(
            meeting_id="m1",
            filename="code_switched.txt",
            content=load_fixture("code_switched.txt"),
            title="Standup",
            meeting_date=MEETING_DATE,
            participants=[
                Participant(participant_id="p-arjun", name="Arjun"),
                Participant(participant_id="p-priya", name="Priya"),
            ],
        ),
        _ctx(),
    )
    assert state.resolved[0].owner_participant_id == "p-priya"
    assert state.resolved[0].due_date == date(2026, 8, 10)


async def test_cross_meeting_recall_surfaces_a_prior_commitment():
    from datetime import datetime, timezone

    from app.adapters.memory.memory import InMemoryMemoryStore
    from app.domain.models import MemoryRecord

    store = InMemoryMemoryStore()
    await store.index(
        MemoryRecord(
            memory_id="old",
            candidate_id="old-c0",
            meeting_id="previous-meeting",
            meeting_title="Last week",
            meeting_date="2026-07-29",
            text="Rohit will finish the API migration",
            created_at=datetime.now(timezone.utc),
        )
    )
    state, _ = await build_graph().run(_state(), _ctx(memory_store=store))
    assert state.carried_forward, "a matching prior commitment should be carried forward"
    assert state.carried_forward[0]["memory"]["meeting_id"] == "previous-meeting"


async def test_recall_never_matches_the_meeting_being_processed():
    from app.adapters.memory.memory import InMemoryMemoryStore

    store = InMemoryMemoryStore()
    state, _ = await build_graph().run(_state(), _ctx(memory_store=store))
    # Nothing indexed yet, so nothing to carry forward -- and the current
    # meeting's own items must never count as prior history.
    assert state.carried_forward == []
