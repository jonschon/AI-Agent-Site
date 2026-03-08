# MVP Release Checklist

## Goal
Launch the MVP safely with real agent runs by using a staging-first rollout, then production promotion.

## 1. Preflight (Before Any Deploy)
- Confirm latest branch is `main` and CI/local checks are green.
- Run backend tests: `cd backend && PYTHONPATH=. python3 -m pytest -q`.
- Run smoke check: `make smoke`.
- Verify required env vars are set:
  - `DATABASE_URL`
  - `INTERNAL_API_KEY`
  - `OPENAI_API_KEY` (recommended)
  - `NEXT_PUBLIC_API_BASE`

## 2. Staging Deploy (Real Agents)
- Deploy backend + frontend to staging.
- Point frontend to staging backend (`NEXT_PUBLIC_API_BASE`).
- Enable scheduler/autonomous cycle in staging.
- Run one manual internal cycle after deploy:
  - `POST /v1/internal/agents/run/all` with `x-internal-api-key`.
- Verify endpoints:
  - `/v1/healthz`
  - `/v1/feed`
  - `/v1/signals`
  - `/v1/stats/newsroom`

## 3. Staging Soak (48 Hours)
- Confirm publish cycles are happening on schedule.
- Confirm no sustained high-severity exceptions.
- Check rankings and feed look reasonable (no obvious source domination bugs).
- Check API latency and error rate are stable.
- Confirm OpenAI usage/cost stays within expected daily budget.

## 4. Production Go-Live
- Deploy same artifact/config pattern proven in staging.
- Run one manual post-deploy cycle.
- Verify public endpoints and homepage rendering.
- Confirm scheduler is running.
- Announce go-live only after first successful publish cycle.

## 5. Rollback Plan
- Keep previous backend/frontend release references ready.
- Roll back immediately if any of these occur:
  - repeated failed pipeline runs,
  - broken feed payloads,
  - sustained 5xx on public endpoints,
  - runaway model API cost.
- After rollback, disable scheduler if instability persists.

## 6. Day-1 Ops Rules
- Check `/v1/stats/newsroom` and internal policy status at least 2x daily.
- Keep one-click command ready: `make smoke`.
- Log incidents with timestamp, impact, and fix in `CHANGELOG_MVP.md`.
