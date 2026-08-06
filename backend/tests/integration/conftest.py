"""Integration-test wiring.

Injects the in-memory repository and in-memory issue tracker via
``app.dependency_overrides``. Production code has no switch for this --
the fakes are reachable only from tests, which is the point.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.calendar.memory import InMemoryCalendarClient
from app.adapters.memory.memory import InMemoryMemoryStore
from app.adapters.repositories.memory import InMemoryRepository
from app.adapters.trackers.memory import InMemoryIssueTracker
from app.api import deps
from app.tools.catalog import build_registry
from app.core.config import Settings
from app.main import app


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def tracker() -> InMemoryIssueTracker:
    return InMemoryIssueTracker()


@pytest.fixture
def calendar() -> InMemoryCalendarClient:
    return InMemoryCalendarClient()


@pytest.fixture
def memory_store() -> InMemoryMemoryStore:
    return InMemoryMemoryStore()


@pytest.fixture
def settings() -> Settings:
    # No credentials: the reference extractor is used, so tests never
    # touch Groq or GitHub.
    return Settings(
        mongo_uri="", groq_api_key="", github_token="", github_repo="",
        confidence_threshold=0.75,
    )


@pytest.fixture
def client(repository, tracker, calendar, memory_store, settings) -> TestClient:
    app.dependency_overrides[deps.get_repository] = lambda: repository
    app.dependency_overrides[deps.get_tracker] = lambda: tracker
    app.dependency_overrides[deps.get_calendar] = lambda: calendar
    app.dependency_overrides[deps.get_memory_store] = lambda: memory_store
    app.dependency_overrides[deps.get_tool_registry] = lambda: build_registry()
    app.dependency_overrides[deps.get_app_settings] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def upload(client):
    """Uploads a fixture transcript and returns the upload response body."""
    from tests.conftest import FIXTURES

    def _upload(
        fixture_name: str,
        title: str = "Sprint standup",
        meeting_date: str = "2026-08-05",
        participants: str = "Arjun\nRohit\nMeera\nPriya",
    ) -> dict:
        content = (FIXTURES / fixture_name).read_bytes()
        response = client.post(
            "/meetings",
            files={"file": (fixture_name, content, "text/plain")},
            data={
                "title": title,
                "meeting_date": meeting_date,
                "participants": participants,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _upload
