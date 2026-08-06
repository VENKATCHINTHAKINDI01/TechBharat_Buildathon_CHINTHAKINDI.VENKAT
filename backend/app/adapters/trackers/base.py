"""F014: the issue-tracker seam -- the only way out to the real world.

The brief requires "at least one genuine side effect through a tool
integration"; Nexvi.Meets's is GitHub Issues. This module defines the
narrow interface that side effect travels through, plus the payload
shape a human reviewer approves.

Two implementations:

- ``GitHubIssueTracker`` -- real HTTP calls, used at runtime. Requires
  ``GITHUB_TOKEN`` and ``GITHUB_REPO`` (a sandbox repo, never a live
  production tracker -- the brief is explicit about this).
- ``InMemoryIssueTracker`` -- records payloads instead of sending them.
  Used **only by the test suite**, so the 250+ tests never touch the
  network. It is not selectable at runtime.

Nothing in the extraction or LLM path may import this package. The only
caller is the approval service, and only after a passing ``GateDecision``
and an explicit human ``ReviewDecision``.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class IssuePayload(BaseModel):
    """The exact payload a reviewer approves and that is sent upstream.

    "Nothing is created, sent or posted until a person sees the exact
    payload and approves it" -- so this object is what the review screen
    displays, what the reviewer may edit, what gets sent, and what is
    written to the audit log. One shape for all four, so they cannot
    drift apart.
    """

    title: str
    body: str
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)


class CreatedIssue(BaseModel):
    number: int
    url: str


class IssueTrackerError(RuntimeError):
    """Raised when the tracker cannot create an issue. Never swallowed:
    a failed side effect must surface to the reviewer and the audit log,
    not be reported as success."""


@runtime_checkable
class IssueTracker(Protocol):
    name: str

    async def create_issue(self, payload: IssuePayload) -> CreatedIssue: ...
