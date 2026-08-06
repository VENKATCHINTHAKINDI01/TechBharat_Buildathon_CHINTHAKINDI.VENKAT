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
