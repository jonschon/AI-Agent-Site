# AI News Platform MVP

Techmeme-inspired, agent-run AI ecosystem news platform.

MVP scope is intentionally locked to:
- crawl -> normalize -> cluster -> summarize -> rank -> publish
- homepage feed + story/category/search views
- internal operational endpoints for runs/exceptions/basic policy health
- no additional platform modules until post-MVP stabilization
- frontend includes resilient loading/empty/error states so feed remains usable during backend/API issues
- core public API contracts are covered by payload-shape tests to prevent breaking frontend changes

## Stack
- Frontend: Next.js (`frontend/`)
- Backend: FastAPI + SQLAlchemy (`backend/`)
- Database: PostgreSQL (with pgvector image in compose)
- Queue/cache (reserved for worker scaling): Redis

## Quick Start
1. Start infra:
   - `docker compose up -d`
2. Backend:
   - `cd backend`
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -e .[dev]`
   - `export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ainews`
   - `uvicorn app.main:app --reload --port 8000`
3. Run first pipeline cycle:
   - `curl -X POST http://localhost:8000/v1/internal/agents/run/all -H "x-internal-api-key: dev-internal-key"`
4. Frontend:
   - `cd frontend`
   - `npm install`
   - `NEXT_PUBLIC_API_BASE=http://localhost:8000/v1 npm run dev`

## MVP Smoke Check
- Run a full local MVP verification with:
  - `make smoke`
- This command will:
  - boot backend
  - run full internal agent pipeline once
  - verify `/v1/feed`, `/v1/signals`, and `/v1/stats/newsroom`

## Implemented MVP Scope
- Agent pipeline (crawler, normalization, embedding, clustering, summarization+tagging, ranking, publishing, QA)
- Feed-driven crawler with per-source RSS config and URL canonicalization
- Scored clustering using semantic + lexical/entity overlap with configurable thresholds
- Automatic cluster merge stage to consolidate near-duplicate active stories
- Ranking now uses real source authority/diversity, recency, discussion signals, and tag confidence
- Internal agent-ops endpoints for autonomous quality metrics and policy evaluation
- Autonomous policy-gated cycle that can hold publishing and raise escalation exceptions
- Scheduler now defaults to autonomous policy-gated cycles for unattended operation
- Self-healing automation: stale low-severity exception auto-resolution and source cooldown/backoff
- Agent memory + policy tuning: dynamic clustering threshold and crawl aggressiveness controls
- Story lifecycle with balanced decay caps (lead/major/quick)
- Public APIs (`/v1/feed`, `/v1/stories`, `/v1/signals`, `/v1/search`, stats, health)
- Internal APIs for agent runs and exception handling
- Next.js UI with desktop two-column and mobile single-column behavior

## Deploy from GitHub
Use `DEPLOYMENT.md`.

Fastest route:
1. Open Render and create a Blueprint from this repo.
2. It will use `render.yaml` to create backend + frontend services.
3. Set env vars:
   - Backend: `DATABASE_URL`, `INTERNAL_API_KEY`
   - Frontend: `NEXT_PUBLIC_API_BASE` = `https://<backend-domain>/v1`
4. Trigger first publish cycle:
   - `POST /v1/internal/agents/run/all` with `x-internal-api-key`.

After that, Render gives you the frontend public URL.

## Notes
- `app/services/model_gateway.py` now supports OpenAI-backed embeddings + summaries when `OPENAI_API_KEY` is set.
- If OpenAI is unavailable, the gateway automatically falls back to deterministic local behavior.
