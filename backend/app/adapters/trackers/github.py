"""Real GitHub Issues implementation.

Uses the REST API directly via httpx rather than a SDK: one endpoint,
no extra dependency, and the exact request body stays visible in the
code (and therefore in the audit log) instead of being assembled inside
a library.
"""
from __future__ import annotations

import httpx

from app.adapters.trackers.base import CreatedIssue, IssuePayload, IssueTrackerError
from app.core.config import Settings, get_settings


class GitHubIssueTracker:
    name = "github"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        # Fail at construction, not mid-approval: if credentials are
        # missing we want to know before a reviewer has clicked approve.
        self._token, self._repo = self._settings.require_github()

    @property
    def repo(self) -> str:
        return self._repo

    async def create_issue(self, payload: IssuePayload) -> CreatedIssue:
        url = f"{self._settings.github_api_base}/repos/{self._repo}/issues"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        body = {"title": payload.title, "body": payload.body}
        if payload.labels:
            body["labels"] = payload.labels
        if payload.assignees:
            body["assignees"] = payload.assignees

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise IssueTrackerError(f"GitHub request failed: {exc}") from exc

        if response.status_code not in (200, 201):
            raise IssueTrackerError(
                f"GitHub returned {response.status_code} creating an issue in "
                f"{self._repo}: {response.text[:400]}"
            )

        data = response.json()
        return CreatedIssue(number=data["number"], url=data["html_url"])
