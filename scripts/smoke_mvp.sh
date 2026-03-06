#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
API_BASE="${API_BASE:-http://127.0.0.1:8000/v1}"
INTERNAL_API_KEY="${INTERNAL_API_KEY:-dev-internal-key}"

UVICORN_PID=""

cleanup() {
  if [[ -n "$UVICORN_PID" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
    kill "$UVICORN_PID" >/dev/null 2>&1 || true
    wait "$UVICORN_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "[smoke] Starting backend on 127.0.0.1:8000"
(
  cd "$BACKEND_DIR"
  PYTHONPATH=. python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/ai_news_smoke_uvicorn.log 2>&1
) &
UVICORN_PID=$!

echo "[smoke] Waiting for /healthz"
python3 - <<'PY'
import sys
import time
import urllib.request

url = "http://127.0.0.1:8000/v1/healthz"
for _ in range(50):
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status == 200:
                print("[smoke] Backend is healthy")
                sys.exit(0)
    except Exception:
        pass
    time.sleep(0.2)
print("[smoke] Backend did not become healthy in time")
sys.exit(1)
PY

echo "[smoke] Triggering full agent pipeline"
python3 - <<PY
import json
import sys
import urllib.request

url = "${API_BASE}/internal/agents/run/all"
req = urllib.request.Request(url, method="POST", headers={"x-internal-api-key": "${INTERNAL_API_KEY}"})
with urllib.request.urlopen(req, timeout=30) as resp:
    payload = json.loads(resp.read().decode("utf-8"))
if "results" not in payload:
    print("[smoke] Missing pipeline results in response")
    sys.exit(1)
print("[smoke] Pipeline run returned agents:", ", ".join(payload["results"].keys()))
PY

echo "[smoke] Validating key public endpoints"
python3 - <<PY
import json
import sys
import urllib.request

api_base = "${API_BASE}"
endpoints = [
    ("/feed", ["published_at", "major_stories", "quick_updates"]),
    ("/signals", None),
    ("/stats/newsroom", ["articles_processed", "stories_detected"]),
]
for path, required_keys in endpoints:
    url = f"{api_base}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        if resp.status != 200:
            print(f"[smoke] {path} returned status {resp.status}")
            sys.exit(1)
        payload = json.loads(resp.read().decode("utf-8"))
    if required_keys is not None:
        for key in required_keys:
            if key not in payload:
                print(f"[smoke] {path} missing key: {key}")
                sys.exit(1)
    print(f"[smoke] {path} OK")

print("[smoke] MVP smoke check passed")
PY
