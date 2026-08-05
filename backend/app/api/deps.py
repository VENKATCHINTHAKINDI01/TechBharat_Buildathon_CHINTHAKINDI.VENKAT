"""FastAPI dependency wiring.

The repository and tracker are resolved through overridable providers so
the test suite can inject in-memory implementations via
``app.dependency_overrides`` without the production code ever offering a
"use fake storage" switch. At runtime these only ever construct the real
MongoDB repository and the real GitHub tracker, and raise a clear
``MissingCredentialError`` if their credentials are absent.
"""
from __future__ import annotations

from functools import lru_cache

from app.adapters.repositories.mongo import MongoRepository
from app.adapters.trackers.github import GitHubIssueTracker
from app.core.config import Settings, get_settings


@lru_cache
def _mongo_repository() -> MongoRepository:
    return MongoRepository()


def get_repository():
    """Runtime persistence. Overridden in tests with InMemoryRepository."""
    return _mongo_repository()


def get_tracker():
    """Runtime issue tracker. Overridden in tests with InMemoryIssueTracker.

    Constructed per-request rather than cached so that a credential fixed
    in ``.env`` mid-session takes effect on the next request instead of
    requiring a restart.
    """
    return GitHubIssueTracker()


def get_app_settings() -> Settings:
    return get_settings()
