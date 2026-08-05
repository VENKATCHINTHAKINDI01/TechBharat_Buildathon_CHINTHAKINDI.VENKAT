#!/usr/bin/env bash
# CommitGuard deterministic verification.
# Exits 0 only if the repository is genuinely in a passing, runnable state.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python3}

echo "== verify: feature_list.json schema =="
$PY - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("feature_list.json").read_text())
assert data.get("project") == "CommitGuard", "project name mismatch"
features = data.get("features")
assert isinstance(features, list) and features, "no features"

ids = set()
for f in features:
    for key in ("id", "priority", "name", "status", "depends_on"):
        assert key in f, f"feature missing '{key}': {f}"
    assert f["status"] in ("todo", "in_progress", "done"), f"bad status: {f}"
    assert f["id"] not in ids, f"duplicate id: {f['id']}"
    ids.add(f["id"])

for f in features:
    for dep in f["depends_on"]:
        assert dep in ids, f"unknown dependency {dep} in {f['id']}"
    # A feature cannot be done while something it depends on is not.
    if f["status"] == "done":
        for dep in f["depends_on"]:
            dep_status = next(x["status"] for x in features if x["id"] == dep)
            assert dep_status == "done", f"{f['id']} is done but depends on {dep} ({dep_status})"

in_progress = [f["id"] for f in features if f["status"] == "in_progress"]
assert len(in_progress) <= 1, f"more than one feature in_progress: {in_progress}"

done = sum(1 for f in features if f["status"] == "done")
print(f"ok: {len(features)} features, {done} done, {len(in_progress)} in_progress")
PY

echo "== verify: required docs exist and are non-empty =="
for f in README.md AGENTS.md CLAUDE.md progress.md legacy/README.md \
         docs/product.md docs/architecture.md docs/data-contracts.md \
         docs/acceptance-tests.md docs/demo-script.md docs/maker-checker-loop.md \
         prompts/maker.md prompts/checker.md backend/.env.example; do
  test -s "$f" || { echo "FAIL: $f missing or empty"; exit 1; }
done
echo "ok"

echo "== verify: no secrets committed =="
if git ls-files --error-unmatch backend/.env >/dev/null 2>&1; then
  echo "FAIL: backend/.env is tracked by git"; exit 1
fi
echo "ok"

echo "== verify: evaluation fixtures present =="
$PY - <<'PY'
import json
from pathlib import Path

labels = json.loads(Path("tests/fixtures/labels.json").read_text())
missing = [
    t["fixture"] for t in labels["transcripts"]
    if not (Path("tests/fixtures") / t["fixture"]).is_file()
]
assert not missing, f"labelled fixtures missing from disk: {missing}"
print(f"ok: {len(labels['transcripts'])} labelled transcripts")
PY

echo "== verify: backend imports cleanly =="
cd backend
PYTHONPATH="$(pwd)" $PY -c "import app.main" || { echo "FAIL: app.main failed to import"; exit 1; }
echo "ok"

echo "== verify: backend test suite =="
PYTHONPATH="$(pwd)" $PY -m pytest -q tests || { echo "FAIL: tests failed"; exit 1; }
cd ..

echo "== verify: legacy tree is archived, not imported =="
if grep -rn "from legacy\|import legacy" backend/app backend/tests >/dev/null 2>&1; then
  echo "FAIL: live code imports from legacy/"; exit 1
fi
echo "ok"

echo "== verify: frontend =="
$PY -c "import json; json.load(open('frontend/package.json'))"
if [ -d frontend/node_modules ]; then
  (cd frontend && npm run build --silent >/dev/null) || { echo "FAIL: frontend build failed"; exit 1; }
  echo "ok (built)"
else
  echo "ok (package.json valid; run 'npm install' in frontend/ to enable the build check)"
fi

echo
echo "verify.sh: all checks passed"
