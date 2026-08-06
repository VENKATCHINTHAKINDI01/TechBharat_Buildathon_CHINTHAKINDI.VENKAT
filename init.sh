#!/usr/bin/env bash
set -euo pipefail
echo "== Nexvi.Meets initialization =="
if [ ! -f "AGENTS.md" ]; then
  echo "ERROR: run from repository root"
  exit 1
fi
echo "[1/5] Checking Python..."
python3 --version
echo "[2/5] Checking Node..."
if command -v node >/dev/null 2>&1; then
  node --version
else
  echo "WARN: Node not installed yet"
fi
echo "[3/5] Checking feature list..."
python3 - <<'PY'
import json
from pathlib import Path
p = Path("feature_list.json")
data = json.loads(p.read_text())
assert data["project"] == "Nexvi.Meets"
assert len(data["features"]) > 0
print(f"features: {len(data['features'])}")
PY
echo "[4/5] Checking required harness files..."
for f in AGENTS.md CLAUDE.md progress.md docs/product.md docs/architecture.md docs/data-contracts.md docs/acceptance-tests.md; do
  test -f "$f" || { echo "Missing $f"; exit 1; }
done
echo "[5/5] Running verification..."
bash scripts/verify.sh
echo "Initialization complete."
