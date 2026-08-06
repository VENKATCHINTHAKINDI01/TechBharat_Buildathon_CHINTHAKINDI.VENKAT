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
for f in README.md AGENTS.md CLAUDE.md progress.md \
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

echo "== verify: the safety boundary holds structurally =="
$PY - <<'PY'
import re
import sys
from pathlib import Path

APP = Path("backend/app")
failures = []

# 1. Extraction and the agents must not import a side-effecting adapter
#    directly -- they may only reach one through the tool registry.
for area in ("services/extraction", "agents"):
    for path in (APP / area).rglob("*.py"):
        text = path.read_text()
        for forbidden in ("adapters.trackers", "adapters.calendar"):
            if forbidden in text:
                failures.append(f"{path} imports {forbidden} directly")

# 2. Only the approval service may invoke a side-effecting tool.
SIDE_EFFECTING = ("github_issue", "calendar_invite", "memory_index", "notification")
ALLOWED = {APP / "services" / "approval.py"}
pattern = re.compile(r"""invoke\(\s*["'](%s)["']""" % "|".join(SIDE_EFFECTING))
for path in APP.rglob("*.py"):
    if path in ALLOWED or path.name == "catalog.py":
        continue
    if pattern.search(path.read_text()):
        failures.append(f"{path} invokes a side-effecting tool outside approval.py")

# 3. The gate must not accept free text.
gate = (APP / "domain" / "safety" / "gate.py").read_text()
signature = re.search(r"def check_gate\(([^)]*)\)", gate)
assert signature, "check_gate signature not found"
params = [p.split(":")[0].strip() for p in signature.group(1).split(",") if p.strip()]
if params != ["item", "confidence_threshold"]:
    failures.append(f"check_gate signature changed: {params}")

if failures:
    print("FAIL:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ok: extraction/agents cannot reach adapters; only approval.py fires side effects")
PY

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
