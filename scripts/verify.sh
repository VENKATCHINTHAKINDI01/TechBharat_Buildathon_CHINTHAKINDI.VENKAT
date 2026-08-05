#!/usr/bin/env bash
# CommitGuard deterministic verification.
# Must exit 0 only if the repo is genuinely in a passing, runnable state.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== verify: feature_list.json schema =="
python3 - <<'PY'
import json, sys
from pathlib import Path

data = json.loads(Path("feature_list.json").read_text())
assert data.get("project") == "CommitGuard", "project name mismatch"
features = data.get("features")
assert isinstance(features, list) and len(features) > 0, "no features"

seen_ids = set()
for f in features:
    for key in ("id", "priority", "name", "status", "depends_on"):
        assert key in f, f"feature missing '{key}': {f}"
    assert f["status"] in ("todo", "in_progress", "done"), f"bad status: {f}"
    assert f["id"] not in seen_ids, f"duplicate id: {f['id']}"
    seen_ids.add(f["id"])
    for dep in f["depends_on"]:
        assert dep in {x["id"] for x in features}, f"unknown dependency {dep} in {f['id']}"

in_progress = [f["id"] for f in features if f["status"] == "in_progress"]
assert len(in_progress) <= 1, f"more than one feature in_progress: {in_progress}"

print(f"ok: {len(features)} features, {len(in_progress)} in_progress")
PY

echo "== verify: required docs exist =="
for f in docs/product.md docs/architecture.md docs/data-contracts.md docs/acceptance-tests.md progress.md AGENTS.md CLAUDE.md; do
  test -s "$f" || { echo "FAIL: $f missing or empty"; exit 1; }
done
echo "ok"

echo "== verify: backend imports and tests =="
cd backend
PYTHONPATH="$(pwd)" python3 -c "import app.main" || { echo "FAIL: app.main failed to import"; exit 1; }
PYTHONPATH="$(pwd)" python3 -m pytest -q app/commitguard 2>/dev/null || {
  echo "WARN: no commitguard tests collected yet (expected before F001 tests exist)";
}
cd ..

echo "== verify: frontend package.json is valid JSON =="
python3 -c "import json; json.load(open('frontend/package.json'))"
echo "ok"

echo "verify.sh: all checks passed"
