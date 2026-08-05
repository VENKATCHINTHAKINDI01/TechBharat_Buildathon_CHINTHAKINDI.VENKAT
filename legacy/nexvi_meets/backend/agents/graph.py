"""
Phase 2 graph: ingestion -> extraction -> resolution -> dedup -> END.

The human-approval interrupt (review_orchestrator_agent) is NOT wired in
yet -- that's Phase 3. For now, items simply land in Mongo with
status="pending_review" and the review UI (Phase 3) reads/writes them
via plain REST endpoints rather than a graph interrupt. Once Phase 3
lands, this graph gets a real interrupt_before=["review_orchestrator_agent"]
and action_agent/notification_agent get added after it.

LangGraph's exact API shifts a little between minor versions --
this targets the langgraph>=0.2 StateGraph interface. Verify against
`pip show langgraph` if anything here doesn't match your installed version.
"""
from typing import TypedDict, Any

from langgraph.graph import StateGraph, END

from app.agents.ingestion_agent import ingestion_agent
from app.agents.extraction_agent import extraction_agent
from app.agents.resolution_agent import resolution_agent
from app.agents.dedup_agent import dedup_agent


class PipelineState(TypedDict, total=False):
    filename: str
    raw_text: str
    meeting_id: str | None
    meeting: Any
    meeting_date: Any
    attendees: list
    db: Any

    raw_chunks: list
    normalized_transcript: str
    structured_record: Any
    action_item_drafts: list
    resolved_action_items: list
    saved_action_item_ids: list
    error: str | None


def _route_after_extraction(state: PipelineState) -> str:
    return "dedup_agent" if state.get("error") else "resolution_agent"
    # Note: on error we still need SOMETHING to persist the failure state.
    # Wire this to a dedicated error-handling node before demo day rather
    # than silently routing errored state into dedup_agent as-is.


def build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("ingestion_agent", ingestion_agent)
    graph.add_node("extraction_agent", extraction_agent)
    graph.add_node("resolution_agent", resolution_agent)
    graph.add_node("dedup_agent", dedup_agent)

    graph.set_entry_point("ingestion_agent")
    graph.add_edge("ingestion_agent", "extraction_agent")
    graph.add_conditional_edges(
        "extraction_agent",
        _route_after_extraction,
        {"resolution_agent": "resolution_agent", "dedup_agent": "dedup_agent"},
    )
    graph.add_edge("resolution_agent", "dedup_agent")
    graph.add_edge("dedup_agent", END)

    return graph.compile()


_compiled_graph = None


def get_pipeline():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


async def run_pipeline(initial_state: PipelineState) -> PipelineState:
    pipeline = get_pipeline()
    return await pipeline.ainvoke(initial_state)