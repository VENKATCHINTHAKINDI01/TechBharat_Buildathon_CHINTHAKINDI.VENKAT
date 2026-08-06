"""Real GitHub Issues implementation.

Uses the REST API directly via httpx rather than a SDK: one endpoint,
no extra dependency, and the exact request body stays visible in the
code (and therefore in the audit log) instead of being assembled inside
a library.
"""
from __future__ import annotations

import logging

import httpx

from app.adapters.trackers.base import CreatedIssue, IssuePayload, IssueTrackerError
from app.core.config import Settings, get_settings

logger = logging.getLogger("nexvi_meets.github")


def describe_token(token: str) -> str:
    """Which kind of credential this is.

    Fine-grained and classic tokens are fixed on different settings pages
    with different controls, so naming the type turns "check your token
    permissions" into a single link the operator can follow.
    """
    if token.startswith("github_pat_"):
        return "fine-grained"
    if token.startswith("ghp_"):
        return "classic"
    if token.startswith("ghs_"):
        return "app"
    return "unknown"


def _permission_hint(repo: str, token_kind: str) -> str:
    if token_kind == "fine-grained":
        return (
            f"This is a fine-grained token. Open github.com/settings/personal-access-tokens, "
            f"edit it, and check BOTH: (1) Repository access includes {repo}, and "
            f"(2) Repository permissions -> Issues is set to 'Read and write'. "
            "Issues defaults to 'No access', which is almost always the cause."
        )
    if token_kind == "classic":
        return (
            "This is a classic token. Open github.com/settings/tokens, edit it, and tick "
            "the 'repo' scope (or 'public_repo' if the repository is public)."
        )
    return (
        f"The token is not allowed to create issues in {repo}. Grant it issue write access."
    )


def explain_github_failure(status: int, body: str, repo: str, token: str = "") -> str:
    """Turn a GitHub status code into something actionable.

    A bare "422 Unprocessable Entity" tells an operator nothing. These are
    the failures that actually happen when wiring up a sandbox repo, and
    each one has a different fix.
    """
    hints = {
        401: (
            "GITHUB_TOKEN is invalid or expired. Generate a new one at "
            "github.com/settings/tokens."
        ),
        403: (
            f"The token is valid but not allowed to create issues in {repo}. "
            + _permission_hint(repo, describe_token(token))
        ),
        404: (
            f"{repo} was not found. Either it does not exist, it is private and "
            "the token cannot see it, or the name is wrong -- GITHUB_REPO must "
            'be "owner/repo" exactly as it appears in the URL.'
        ),
        410: (
            f"Issues are disabled on {repo}. Enable them in Settings -> "
            "General -> Features -> Issues."
        ),
        422: (
            "GitHub rejected the issue content. The usual cause is an assignee "
            "who is not a collaborator on the repo, or a label the token may "
            "not create."
        ),
    }
    hint = hints.get(status, "")
    return f"GitHub returned {status} for {repo}. {hint} Response: {body[:300]}"


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
            message = explain_github_failure(
                response.status_code, response.text, self._repo, self._token
            )
            # Log the full body: the API response is truncated for the UI,
            # but an operator debugging this wants everything.
            logger.error(
                "GitHub issue creation failed (%s) for %s: %s",
                response.status_code,
                self._repo,
                response.text[:2000],
            )
            raise IssueTrackerError(message)

        data = response.json()
        return CreatedIssue(number=data["number"], url=data["html_url"])
