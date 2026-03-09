# MVP Release Checklist

## Goal
Ship and operate the site in production with predictable behavior, clean rollback, and daily visibility.

## Ownership Split
- Codex-owned (in repo): tests, smoke, live API checks, docs/runbook, pipeline and safety code.
- User-owned (Render UI): deploy clicks, env var management, scheduler setup, domain settings.

## 1. Pre-Deploy Gate (Codex-owned)
Run from repo root:
- `make backend-test`
- `make smoke`
- `API_BASE=https://<backend>.onrender.com/v1 make live-check`

Pass criteria:
- tests are green
- smoke passes end-to-end
- live `/healthz`, `/feed`, `/signals`, `/stats/newsroom` pass shape checks

## 2. Deploy (User-owned in Render)
Backend (`ai-news-backend`):
1. `Manual Deploy` -> `Deploy latest commit`
2. confirm service is `Live`

Frontend (`ai-news-frontend`):
1. `Manual Deploy` -> `Deploy latest commit`
2. confirm service is `Live`

## 3. Post-Deploy Validation (Codex-owned)
Run:
- `API_BASE=https://<backend>.onrender.com/v1 INTERNAL_API_KEY=<key> make live-publish-check`

This verifies live endpoints and triggers one publish cycle.

## 4. Scheduler/Sourcing Check (User-owned + Codex verification)
User in Render:
1. confirm only one scheduler/cron path is active
2. cadence: every 30-45 minutes

Codex verify via API:
- check `/v1/internal/agent-runs` for recurring crawler/normalization/publishing runs

## 5. Rollback Procedure
When to rollback immediately:
- repeated 5xx from public endpoints
- pipeline repeatedly stuck/failed
- bad feed payload shape

Steps:
1. in Render, deploy previous known-good commit for backend
2. deploy matching previous frontend commit
3. run `API_BASE=... make live-check`
4. trigger publish once and re-check homepage

## 6. Daily Ops (Fast)
Twice daily:
- `API_BASE=https://<backend>.onrender.com/v1 make live-check`
- review `/v1/internal/agent-runs` for stuck runs or repeated fails
- spot-check top stories + leaderboard sanity

## 7. Current Production Commands
- Full local gate: `make release-gate`
- Live check only: `API_BASE=https://<backend>.onrender.com/v1 make live-check`
- Live check + publish trigger: `API_BASE=https://<backend>.onrender.com/v1 INTERNAL_API_KEY=<key> make live-publish-check`
