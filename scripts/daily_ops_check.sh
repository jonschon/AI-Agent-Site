#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-}"
INTERNAL_API_KEY="${INTERNAL_API_KEY:-}"

if [[ -z "$API_BASE" ]]; then
  echo "[daily-ops] ERROR: API_BASE is required"
  exit 1
fi
if [[ -z "$INTERNAL_API_KEY" ]]; then
  echo "[daily-ops] ERROR: INTERNAL_API_KEY is required"
  exit 1
fi

echo "[daily-ops] Starting daily checks"
API_BASE="$API_BASE" INTERNAL_API_KEY="$INTERNAL_API_KEY" TRIGGER_PUBLISH=1 ./scripts/live_check.sh

echo "[daily-ops] Triggering leaderboard validation"
python3 - <<PY
import json
import sys
import urllib.request
from urllib.error import HTTPError, URLError

api_base = "${API_BASE}".rstrip("/")
key = "${INTERNAL_API_KEY}"

req = urllib.request.Request(
    f"{api_base}/internal/agents/run/leaderboard_validation",
    method="POST",
    headers={"x-internal-api-key": key},
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        if resp.status != 200:
            print(f"[daily-ops] FAIL leaderboard_validation status={resp.status}")
            sys.exit(1)
except (HTTPError, URLError) as exc:
    print(f"[daily-ops] FAIL leaderboard_validation: {exc}")
    sys.exit(1)

if payload.get("agent") != "leaderboard_validation":
    print(f"[daily-ops] FAIL leaderboard_validation payload={payload}")
    sys.exit(1)
print("[daily-ops] leaderboard_validation OK", payload)

# Short status summary
with urllib.request.urlopen(f"{api_base}/signals", timeout=20) as resp:
    signals = json.loads(resp.read().decode("utf-8"))
rows_summary = []
for signal in signals[:4]:
    data = signal.get("data") if isinstance(signal, dict) else {}
    rows = data.get("rows") if isinstance(data, dict) else []
    rows_summary.append((signal.get("title"), len(rows) if isinstance(rows, list) else 0))
print("[daily-ops] leaderboard rows:", rows_summary)
PY

echo "[daily-ops] PASS"
