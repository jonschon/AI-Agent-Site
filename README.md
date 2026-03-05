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
- Story lifecycle with balanced decay caps (lead/major/quick)
- Public APIs (`/v1/feed`, `/v1/stories`, `/v1/signals`, `/v1/search`, stats, health)
- Internal APIs for agent runs and exception handling
- Next.js UI with desktop two-column and mobile single-column behavior

## Notes
- Embeddings/summaries currently use deterministic local stubs for predictable MVP behavior.
- Replace `app/services/model_gateway.py` with provider-backed implementations for production.
