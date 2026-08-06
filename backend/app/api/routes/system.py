"""Introspection endpoints: agents, tools, and cross-meeting memory.

These exist because "agentic" should be inspectable rather than asserted.
A judge can ask the running system what agents it has, what tools each may
use, which of those tools can touch the outside world, and what it did on
a given meeting — without reading the source.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agents.langgraph_runtime import build_runtime
from app.api import deps
from app.core.config import Settings

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/agents")
async def list_agents(settings: Settings = Depends(deps.get_app_settings)) -> dict:
    graph = build_runtime(settings)
    return {
        "runtime": getattr(graph, "runtime", "inhouse"),
        "requested_runtime": settings.agent_runtime,
        "interrupt_before": getattr(graph, "interrupt_before", "human_review"),
        "agents": graph.describe(),
        "note": (
            "The graph always stops at the human-review interrupt. Resuming is a "
            "separate, human-initiated call; the system cannot resume itself."
        ),
    }


@router.get("/tools")
async def list_tools(registry=Depends(deps.get_tool_registry)) -> dict:
    return {
        "tools": registry.describe(),
        "side_effecting": registry.side_effecting_names,
        "note": (
            "Side-effecting tools cannot be invoked through the registry without a "
            "passing safety-gate decision and an explicit human approval."
        ),
    }


@router.get("/meetings/{meeting_id}/agent-run")
async def agent_run(meeting_id: str, repository=Depends(deps.get_repository)) -> dict:
    run = await repository.get_agent_run(meeting_id)
    if run is None:
        raise HTTPException(404, "No agent run recorded for this meeting")
    return {**run.model_dump(mode="json"), "total_ms": run.total_ms}


@router.get("/memory/search")
async def search_memory(
    q: str = Query(..., min_length=2, description="Free-text query"),
    limit: int = Query(5, ge=1, le=25),
    exclude_meeting_id: str | None = None,
    memory_store=Depends(deps.get_memory_store),
) -> dict:
    """Cross-meeting recall over **approved** commitments only.

    Nothing a reviewer rejected is in here, so this cannot resurface a
    hallucinated commitment as if it were history.
    """
    try:
        hits = await memory_store.search(q, limit=limit, exclude_meeting_id=exclude_meeting_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Memory store unavailable: {exc}")

    return {
        "query": q,
        "results": [
            {"similarity": round(score, 3), **record.model_dump(mode="json")}
            for record, score in hits
        ],
    }


@router.get("/github/check")
async def github_check(settings: Settings = Depends(deps.get_app_settings)) -> dict:
    """Preflight the GitHub integration without creating anything.

    Reads the repo and inspects the token's own permissions, so a
    misconfiguration is discovered before a reviewer approves something
    and watches it fail. Same reasoning as the Mongo probe on /readiness:
    "configured" and "actually works" are different states, and confusing
    them wastes real time.
    """
    import httpx

    if not settings.github_token or not settings.github_repo:
        return {
            "ok": False,
            "reason": "GITHUB_TOKEN and GITHUB_REPO must both be set in backend/.env.",
        }

    url = f"{settings.github_api_base}/repos/{settings.github_repo}"
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "reason": f"Could not reach GitHub: {exc}"}

    if response.status_code != 200:
        from app.adapters.trackers.github import explain_github_failure

        return {
            "ok": False,
            "status": response.status_code,
            "repo": settings.github_repo,
            "reason": explain_github_failure(
                response.status_code, response.text, settings.github_repo
            ),
        }

    repo = response.json()
    permissions = repo.get("permissions", {})
    has_issues = repo.get("has_issues", False)
    can_push = permissions.get("push", False)

    problems = []
    if not has_issues:
        problems.append(
            f"Issues are disabled on {settings.github_repo}. "
            "Enable them in Settings -> General -> Features -> Issues."
        )
    if not can_push:
        problems.append(
            "The token can read this repo but has no write access, so it "
            "cannot create issues. A fine-grained token needs "
            "Repository permissions -> Issues: Read and write."
        )

    return {
        "ok": not problems,
        "repo": repo.get("full_name"),
        "private": repo.get("private"),
        "has_issues": has_issues,
        "permissions": permissions,
        "reason": " ".join(problems) if problems else "Ready to create issues.",
    }
