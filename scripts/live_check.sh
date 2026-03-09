#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-}"
INTERNAL_API_KEY="${INTERNAL_API_KEY:-}"
TRIGGER_PUBLISH="${TRIGGER_PUBLISH:-0}"

if [[ -z "$API_BASE" ]]; then
  echo "[live-check] ERROR: API_BASE is required (example: https://your-backend.onrender.com/v1)"
  exit 1
fi

if [[ "$TRIGGER_PUBLISH" == "1" && -z "$INTERNAL_API_KEY" ]]; then
  echo "[live-check] ERROR: INTERNAL_API_KEY is required when TRIGGER_PUBLISH=1"
  exit 1
fi

echo "[live-check] API_BASE=$API_BASE"

python3 - <<PY
import json
import sys
import urllib.request
from urllib.error import HTTPError, URLError

api_base = "${API_BASE}".rstrip("/")

def fetch(path: str):
    url = f"{api_base}{path}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            if resp.status != 200:
                print(f"[live-check] FAIL {path}: status={resp.status}")
                sys.exit(1)
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        print(f"[live-check] FAIL {path}: {exc}")
        sys.exit(1)

health = fetch("/healthz")
if health.get("status") != "ok":
    print("[live-check] FAIL /healthz payload")
    sys.exit(1)
print("[live-check] /healthz OK")

feed = fetch("/feed")
for key in ("published_at", "major_stories", "quick_updates"):
    if key not in feed:
        print(f"[live-check] FAIL /feed missing key={key}")
        sys.exit(1)
print("[live-check] /feed OK")

signals = fetch("/signals")
if not isinstance(signals, list) or len(signals) == 0:
    print("[live-check] FAIL /signals empty")
    sys.exit(1)
print("[live-check] /signals OK")

stats = fetch("/stats/newsroom")
for key in ("articles_processed", "stories_detected"):
    if key not in stats:
        print(f"[live-check] FAIL /stats/newsroom missing key={key}")
        sys.exit(1)
print("[live-check] /stats/newsroom OK")

stories = []
if feed.get("lead_story"):
    stories.append(feed["lead_story"])
stories += feed.get("major_stories", [])
stories += feed.get("quick_updates", [])
missing_sources = sum(1 for story in stories if not story.get("sources"))
print(f"[live-check] stories={len(stories)} missing_sources={missing_sources}")
PY

if [[ "$TRIGGER_PUBLISH" == "1" ]]; then
  echo "[live-check] Triggering publishing"
  python3 - <<PY
import json
import sys
import urllib.request
from urllib.error import HTTPError, URLError

api_base = "${API_BASE}".rstrip("/")
url = f"{api_base}/internal/agents/run/publishing"
req = urllib.request.Request(
    url,
    method="POST",
    headers={"x-internal-api-key": "${INTERNAL_API_KEY}"},
)
try:
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        if resp.status != 200:
            print(f"[live-check] FAIL publish status={resp.status}")
            sys.exit(1)
except (HTTPError, URLError) as exc:
    print(f"[live-check] FAIL publish: {exc}")
    sys.exit(1)

if payload.get("agent") != "publishing":
    print(f"[live-check] FAIL publish payload={payload}")
    sys.exit(1)
print("[live-check] publish OK", payload)
PY
fi

echo "[live-check] PASS"
