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
    assert set(body["integrations"]) == {"mongo", "groq", "github"}
    assert body["extractor"] in ("groq", "reference")
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


def test_app_does_not_import_legacy_nexvi_modules():
    """The legacy tree is archived, not imported. If this fails, something
    reintroduced a dependency on code that has no safety gate."""
    import app.main  # noqa: F401

    leaked = [
        m
        for m in sys.modules
        if m.startswith(("app.agents", "app.tools", "app.review", "app.roster", "app.db"))
    ]
    assert leaked == [], f"legacy modules imported: {leaked}"
