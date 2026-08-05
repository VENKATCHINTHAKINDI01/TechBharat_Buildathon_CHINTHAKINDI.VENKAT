"""In-memory issue tracker -- test double only.

Records the exact payloads it was asked to create so tests can assert on
them, and hands back plausible issue numbers. Deliberately **not**
selectable at runtime: `app/api/deps.py` only ever constructs the real
GitHub tracker, so there is no configuration mistake that could make a
live demo quietly record issues to nowhere and report success.
"""
from __future__ import annotations

from itertools import count

from app.adapters.trackers.base import CreatedIssue, IssuePayload


class InMemoryIssueTracker:
    name = "memory"

    def __init__(self, repo: str = "example-org/sandbox") -> None:
        self.repo = repo
        self.created: list[IssuePayload] = []
        self._counter = count(1)
        self.fail_next = False  # lets tests exercise the failure path

    async def create_issue(self, payload: IssuePayload) -> CreatedIssue:
        if self.fail_next:
            from app.adapters.trackers.base import IssueTrackerError

            self.fail_next = False
            raise IssueTrackerError("simulated tracker failure")

        self.created.append(payload)
        number = next(self._counter)
        return CreatedIssue(
            number=number, url=f"https://github.com/{self.repo}/issues/{number}"
        )
