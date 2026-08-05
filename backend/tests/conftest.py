"""Shared test fixtures and paths.

The transcript corpus lives at the repository root in ``tests/fixtures/``
rather than under ``backend/`` because it is product data: the demo
script, the evaluation harness, and the docs all reference it directly.
This module is the single place that resolves that path, so moving the
corpus later means editing one line.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"

# Fixed meeting date used across tests so relative-date resolution is
# reproducible regardless of when the suite runs. 2026-08-05 is a Wednesday.
MEETING_DATE = date(2026, 8, 5)

NAMED_FIXTURES = [
    "confirmed_commitment.txt",
    "vague_suggestion.txt",
    "owner_reassignment.txt",
    "deadline_change.txt",
    "disagreement.txt",
    "cancelled_commitment.txt",
    "ambiguous_owner.txt",
    "prompt_injection.txt",
    "code_switched.txt",
]


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def meeting_date() -> date:
    return MEETING_DATE
