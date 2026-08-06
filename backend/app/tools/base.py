"""The tool layer.

The brief's FAQ defines agentic as: *"The system decides what actions are
needed and executes them through tools."* So tools here are first-class,
declared objects with metadata — not loose function calls — and the
registry that owns them is where the safety guarantee is made structural.

Every tool declares whether it is **side-effecting**. A side-effecting
tool physically cannot be invoked through the registry without:

1. a ``GateDecision`` whose ``eligible`` is True, and
2. an explicit human ``ReviewDecision`` that approved it.

That check lives in ``ToolRegistry.invoke`` (see ``registry.py``), so a
future agent — or a future contributor — cannot reach a side effect by
calling a tool directly and forgetting the gate. The refusal is raised,
audited, and tested.

Read-only tools (parsing, resolving, scoring) are unrestricted; they
cannot change anything outside the process.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolSpec:
    """Agent-facing description of a capability."""

    name: str
    description: str
    side_effecting: bool = False
    # Which external system this touches. None for pure computation.
    system: Optional[str] = None
    # Free-form tags used by the UI and by docs generation.
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "side_effecting": self.side_effecting,
            "system": self.system,
            "tags": list(self.tags),
        }


@runtime_checkable
class Tool(Protocol):
    spec: ToolSpec

    async def __call__(self, **kwargs: Any) -> Any: ...


class ToolError(RuntimeError):
    """A tool failed. Never swallowed: a failed side effect must surface
    to the reviewer and the audit log, not be reported as success."""


class ToolPermissionError(PermissionError):
    """A side-effecting tool was invoked without a passing gate decision
    and an explicit human approval.

    This is not an edge case to handle gracefully and continue past — it
    means something tried to take an external action the system had not
    been authorised to take.
    """


class FunctionTool:
    """Wraps an async callable as a Tool.

    Business logic lives in ``app/services`` and ``app/adapters``; this
    class only attaches the agent-facing metadata, so the same logic can
    be unit-tested directly without going through the registry.
    """

    def __init__(self, spec: ToolSpec, fn: Callable[..., Awaitable[Any]]) -> None:
        self.spec = spec
        self._fn = fn

    async def __call__(self, **kwargs: Any) -> Any:
        return await self._fn(**kwargs)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        kind = "side-effecting" if self.spec.side_effecting else "read-only"
        return f"<Tool {self.spec.name} ({kind})>"
