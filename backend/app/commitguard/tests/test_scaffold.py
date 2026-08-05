"""F001 acceptance tests -- see docs/acceptance-tests.md#f001.

Covers:
- app.main imports cleanly with the commitguard router mounted
- GET /health (existing Nexvi.Meets endpoint) still returns 200
- GET /commitguard/health returns 200 with the expected shape
- feature_list.json at the repo root is valid and well-formed
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_existing_nexvi_health_endpoint_untouched():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_commitguard_health_endpoint():
    resp = client.get("/commitguard/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "component": "commitguard"}


def test_feature_list_json_is_valid():
    # backend/app/commitguard/tests/test_scaffold.py -> repo root is 5 parents up
    repo_root = Path(__file__).resolve().parents[4]
    data = json.loads((repo_root / "feature_list.json").read_text())

    assert data["project"] == "CommitGuard"
    ids = [f["id"] for f in data["features"]]
    assert len(ids) == len(set(ids)), "duplicate feature ids"
    assert "F001" in ids

    known_ids = set(ids)
    for feature in data["features"]:
        assert feature["status"] in ("todo", "in_progress", "done")
        for dep in feature["depends_on"]:
            assert dep in known_ids
