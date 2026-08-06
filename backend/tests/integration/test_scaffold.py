"""F001 acceptance tests -- see docs/acceptance-tests.md#f001.

CommitGuard is now the application itself rather than a router mounted
inside the legacy Nexvi.Meets app (see legacy/README.md), so the health
endpoint lives at /health.
"""
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["component"] == "commitguard"
    assert body["app"] == "CommitGuard"


def test_readiness_reports_integration_configuration():
    resp = client.get("/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["integrations"]) == {
        "mongo",
        "groq",
        "github",
        "sarvam",
        "calendar",
        "memory",
    }
    assert body["extractor"] in ("groq", "reference")
    assert body["normalizer"] in ("sarvam", "none")
    assert body["agent_runtime"] in ("inhouse", "langgraph")
    assert isinstance(body["enabled_side_effects"], list)
    assert 0.0 <= body["confidence_threshold"] <= 1.0


def test_feature_list_json_is_valid():
    data = json.loads((REPO_ROOT / "feature_list.json").read_text())

    assert data["project"] == "CommitGuard"
    ids = [f["id"] for f in data["features"]]
    assert len(ids) == len(set(ids)), "duplicate feature ids"
    assert "F001" in ids

    known_ids = set(ids)
    for feature in data["features"]:
        assert feature["status"] in ("todo", "in_progress", "done")
        for dep in feature["depends_on"]:
            assert dep in known_ids


def test_no_legacy_package_remains_importable():
    """The pre-CommitGuard tree was absorbed and deleted. `app.agents` and
    `app.tools` are now first-class CommitGuard packages; what must NOT
    exist is the old ungated Nexvi.Meets code."""
    import app.main  # noqa: F401

    leaked = [
        m
        for m in sys.modules
        if m.startswith(("app.review", "app.roster", "app.db", "app.integrations", "app.websocket"))
    ]
    assert leaked == [], f"pre-CommitGuard modules imported: {leaked}"


def test_side_effecting_tools_are_exactly_the_four_expected():
    """A new external action must be a deliberate, reviewed addition --
    not something that appears because someone wrapped a client."""
    from app.tools import build_registry

    assert build_registry().side_effecting_names == [
        "calendar_invite",
        "github_issue",
        "memory_index",
        "notification",
    ]
