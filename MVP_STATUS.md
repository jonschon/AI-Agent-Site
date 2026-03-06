# MVP Status

## Snapshot
- Project: AI News Platform MVP (Techmeme-inspired, agent-run)
- Branch: `main`
- Latest commit: `e173f19`
- Repo: https://github.com/jonschon/AI-Agent-Site
- Current state: core MVP implemented and test-stable

## Locked MVP Scope
- Pipeline: crawl -> normalize -> cluster -> summarize -> rank -> publish
- UI: homepage feed + story/category/search pages
- Ops: internal runs/exceptions/policy health endpoints
- Stability: loading/empty/error UI states + API contract tests + smoke command
- Out of scope for now: new platform modules and non-MVP feature expansion

## Done
- Backend schema + API routes + internal endpoints
- Feed-driven crawler with source configs and URL canonicalization
- Semantic+lexical clustering and merge step
- AI summarization/embedding with OpenAI + fallback
- Ranking with real source/diversity/recency/discussion signals
- Policy-gated autonomous cycle and scheduler
- Self-heal + adaptive tuning controls
- Frontend with responsive feed and resilient states
- Test coverage: unit/integration/contract/smoke layers

## Current Verification
- Backend tests: `28 passed`
- Local smoke command: `make smoke` (passes)
- Frontend build check: not run in this environment (no npm available here)

## Key Run Commands
- Backend tests: `cd backend && PYTHONPATH=. python3 -m pytest -q`
- Smoke check: `make smoke`
- Run backend: `cd backend && PYTHONPATH=. uvicorn app.main:app --reload --port 8000`
- Run frontend: `cd frontend && NEXT_PUBLIC_API_BASE=http://localhost:8000/v1 npm run dev`

## Env Vars (Core)
- `DATABASE_URL`
- `INTERNAL_API_KEY`
- `OPENAI_API_KEY` (optional but recommended)
- `NEXT_PUBLIC_API_BASE` (frontend)

## Next 3 MVP Tasks
1. Add frontend build/typecheck command to smoke flow (run when npm available).
2. Add minimal API versioned fixture snapshots for `/v1/stories` and `/v1/feed/sections`.
3. Final MVP release checklist doc (`MVP_RELEASE_CHECKLIST.md`) with deploy and rollback steps.

## Thread Handoff Template
For a new chat, paste only:
- Latest commit hash
- This file (`MVP_STATUS.md`)
- One atomic task request
