# AI News Platform MVP

Techmeme-inspired, agent-run AI ecosystem news platform.

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

## Implemented MVP Scope
- Agent pipeline (crawler, normalization, embedding, clustering, summarization+tagging, ranking, publishing, QA)
- Feed-driven crawler with per-source RSS config and URL canonicalization
- Scored clustering using semantic + lexical/entity overlap with configurable thresholds
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
