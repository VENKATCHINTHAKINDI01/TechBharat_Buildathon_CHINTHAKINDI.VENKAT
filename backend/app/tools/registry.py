"""The tool registry — where authorisation is enforced structurally.

``AGENTS.md``: *the LLM may interpret the meeting; deterministic code
decides whether an external action is allowed.* The registry is the
second half of that sentence made mechanical.

An agent asks the registry to invoke a tool by name. If the tool is
side-effecting, the registry demands proof of authorisation — a passing
``GateDecision`` and an approving ``ReviewDecision`` for the *same*
candidate — before it will call anything. No proof, no call, and the
refusal is raised rather than logged and stepped over.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from app.domain.models import GateDecision, ReviewDecision, ReviewDecisionValue
from app.tools.base import Tool, ToolPermissionError, ToolSpec

_APPROVING = {ReviewDecisionValue.approved, ReviewDecisionValue.edited_and_approved}


class Authorization:
    """Evidence that a human authorised a specific candidate's side effect.

    Constructed only by the approval service. Carrying the two decisions
    together (rather than a boolean) means the audit log can always say
    *why* an action was permitted, not merely that it was.
    """

    def __init__(self, gate: GateDecision, review: ReviewDecision) -> None:
        self.gate = gate
        self.review = review

    @property
    def candidate_id(self) -> str:
        return self.gate.candidate_id

    def validate(self, tool_name: str) -> None:
        if not self.gate.eligible:
            raise ToolPermissionError(
                f"Refusing to run side-effecting tool '{tool_name}': the safety gate "
                f"blocked candidate {self.gate.candidate_id} "
                f"({'; '.join(self.gate.reasons) or 'no reason recorded'})."
            )
        if self.review.decision not in _APPROVING:
            raise ToolPermissionError(
                f"Refusing to run side-effecting tool '{tool_name}': candidate "
                f"{self.gate.candidate_id} has review decision "
                f"'{self.review.decision.value}', not an approval."
            )
        if self.review.candidate_id != self.gate.candidate_id:
            raise ToolPermissionError(
                f"Refusing to run side-effecting tool '{tool_name}': the approval is "
                f"for candidate {self.review.candidate_id} but the gate decision is "
                f"for {self.gate.candidate_id}. An approval cannot be reused across items."
            )


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)
        # Every invocation is appended here so an agent step can report
        # exactly which tools it used without threading a logger through.
        self.calls: list[str] = []

    def register(self, tool: Tool) -> None:
        if tool.spec.name in self._tools:
            raise ValueError(f"tool already registered: {tool.spec.name}")
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(
                f"unknown tool '{name}'. Registered: {sorted(self._tools)}"
            ) from None

    def has(self, name: str) -> bool:
        return name in self._tools

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def describe(self) -> list[dict[str, Any]]:
        return [s.as_dict() for s in sorted(self.specs(), key=lambda s: s.name)]

    @property
    def side_effecting_names(self) -> list[str]:
        return sorted(s.name for s in self.specs() if s.side_effecting)

    async def invoke(
        self, name: str, *, authorization: Optional[Authorization] = None, **kwargs: Any
    ) -> Any:
        """Invoke a registered tool.

        Side-effecting tools require ``authorization``. This is the single
        chokepoint every external action passes through.
        """
        tool = self.get(name)

        if tool.spec.side_effecting:
            if authorization is None:
                raise ToolPermissionError(
                    f"Refusing to run side-effecting tool '{name}' without authorization. "
                    "Side effects require a passing safety-gate decision and an explicit "
                    "human approval; see app/services/approval.py."
                )
            authorization.validate(name)

        self.calls.append(name)
        return await tool(**kwargs)

    def reset_calls(self) -> list[str]:
        used, self.calls = self.calls, []
        return used
