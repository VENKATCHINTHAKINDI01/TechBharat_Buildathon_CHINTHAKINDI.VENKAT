"""The tool registry is where "zero unapproved actions" becomes structural.

These tests exist to make that guarantee falsifiable: if someone removes
the authorization check, several of these fail loudly.
"""
from datetime import datetime, timezone

import pytest

from app.domain.models import GateDecision, ReviewDecision, ReviewDecisionValue
from app.tools.base import FunctionTool, ToolPermissionError, ToolSpec
from app.tools.registry import Authorization, ToolRegistry

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def _gate(candidate_id="c1", eligible=True, reasons=None) -> GateDecision:
    return GateDecision(
        candidate_id=candidate_id, eligible=eligible, reasons=reasons or [], checked_at=NOW
    )


def _review(candidate_id="c1", decision=ReviewDecisionValue.approved) -> ReviewDecision:
    return ReviewDecision(
        candidate_id=candidate_id,
        reviewer="vyas",
        decision=decision,
        final_payload={"title": "x"} if decision != ReviewDecisionValue.rejected else None,
        decided_at=NOW,
    )


async def _noop(**kwargs):
    return "ran"


def _registry() -> ToolRegistry:
    return ToolRegistry(
        [
            FunctionTool(ToolSpec("safe_tool", "read-only"), _noop),
            FunctionTool(ToolSpec("danger", "external", side_effecting=True, system="github"), _noop),
        ]
    )


async def test_read_only_tool_needs_no_authorization():
    assert await _registry().invoke("safe_tool") == "ran"


async def test_side_effecting_tool_without_authorization_is_refused():
    with pytest.raises(ToolPermissionError, match="without authorization"):
        await _registry().invoke("danger")


async def test_side_effecting_tool_with_full_authorization_runs():
    auth = Authorization(gate=_gate(), review=_review())
    assert await _registry().invoke("danger", authorization=auth) == "ran"


async def test_blocked_gate_refuses_even_with_an_approval():
    """A human cannot approve past the gate. This is the whole point."""
    auth = Authorization(
        gate=_gate(eligible=False, reasons=["no owner resolved"]), review=_review()
    )
    with pytest.raises(ToolPermissionError, match="safety gate blocked"):
        await _registry().invoke("danger", authorization=auth)


async def test_rejection_is_not_an_approval():
    auth = Authorization(gate=_gate(), review=_review(decision=ReviewDecisionValue.rejected))
    with pytest.raises(ToolPermissionError, match="not an approval"):
        await _registry().invoke("danger", authorization=auth)


async def test_edited_and_approved_counts_as_an_approval():
    auth = Authorization(
        gate=_gate(), review=_review(decision=ReviewDecisionValue.edited_and_approved)
    )
    assert await _registry().invoke("danger", authorization=auth) == "ran"


async def test_an_approval_cannot_be_reused_for_a_different_candidate():
    """Otherwise approving one item would authorise creating another."""
    auth = Authorization(gate=_gate(candidate_id="c1"), review=_review(candidate_id="c2"))
    with pytest.raises(ToolPermissionError, match="cannot be reused"):
        await _registry().invoke("danger", authorization=auth)


async def test_registry_records_which_tools_were_called():
    registry = _registry()
    await registry.invoke("safe_tool")
    await registry.invoke("safe_tool")
    assert registry.reset_calls() == ["safe_tool", "safe_tool"]
    assert registry.reset_calls() == []


def test_unknown_tool_raises_with_a_useful_message():
    with pytest.raises(KeyError, match="unknown tool"):
        _registry().get("nope")


def test_duplicate_registration_is_rejected():
    registry = _registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FunctionTool(ToolSpec("danger", "dup", side_effecting=True), _noop))


def test_catalog_marks_exactly_the_expected_tools_as_side_effecting():
    from app.tools import build_registry

    registry = build_registry()
    assert registry.side_effecting_names == [
        "calendar_invite",
        "github_issue",
        "memory_index",
        "notification",
    ]
    for spec in registry.specs():
        assert spec.description, f"{spec.name} has no description"


# --- GitHub failure translation --------------------------------------------
#
# A bare "GitHub returned 403" sent an operator hunting through server
# logs. Each status has a different fix, and the message should say which.


def test_github_failures_explain_the_actual_fix():
    from app.adapters.trackers.github import explain_github_failure

    assert "invalid or expired" in explain_github_failure(401, "", "org/repo")
    assert "Read and write" in explain_github_failure(403, "", "org/repo", "github_pat_x")
    assert "not found" in explain_github_failure(404, "", "org/repo")
    assert "Issues are disabled" in explain_github_failure(410, "", "org/repo")
    assert "assignee" in explain_github_failure(422, "", "org/repo")


def test_the_repo_name_appears_so_a_typo_is_obvious():
    from app.adapters.trackers.github import explain_github_failure

    message = explain_github_failure(404, "Not Found", "VENKAT/typo_repo")
    assert "VENKAT/typo_repo" in message
    assert "owner/repo" in message


def test_an_unmapped_status_still_includes_the_response_body():
    from app.adapters.trackers.github import explain_github_failure

    message = explain_github_failure(500, "upstream exploded", "org/repo")
    assert "500" in message
    assert "upstream exploded" in message


async def test_a_github_rejection_surfaces_its_reason_through_the_api(monkeypatch):
    """The 502 body must lead with the cause, not a generic sentence."""
    import httpx

    from app.adapters.trackers.github import GitHubIssueTracker
    from app.adapters.trackers.base import IssuePayload, IssueTrackerError
    from app.core.config import Settings

    # A realistic fine-grained token, so the hint names the right settings page.
    settings = Settings(github_token="github_pat_11ABCDEF", github_repo="org/repo")
    tracker = GitHubIssueTracker(settings)

    async def fake_post(*args, **kwargs):
        return httpx.Response(403, text='{"message":"Resource not accessible"}')

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        post = staticmethod(fake_post)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())

    with pytest.raises(IssueTrackerError, match="Read and write"):
        await tracker.create_issue(IssuePayload(title="t", body="b"))


def test_the_hint_matches_the_token_type():
    """Fine-grained and classic tokens are fixed on different pages with
    different controls; naming the type saves a wrong-page detour."""
    from app.adapters.trackers.github import describe_token, explain_github_failure

    assert describe_token("github_pat_abc") == "fine-grained"
    assert describe_token("ghp_abc") == "classic"
    assert describe_token("weird") == "unknown"

    fine = explain_github_failure(403, "", "org/repo", "github_pat_abc")
    assert "personal-access-tokens" in fine
    assert "Issues is set to 'Read and write'" in fine

    classic = explain_github_failure(403, "", "org/repo", "ghp_abc")
    assert "settings/tokens" in classic
    assert "'repo' scope" in classic
