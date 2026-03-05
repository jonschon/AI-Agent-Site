# Deployment Guide

## Option A: Fastest path (Render Blueprint)
1. In Render, create a new Blueprint and point it to this GitHub repo.
2. Render will read `render.yaml` and create:
   - `ai-news-backend` (Docker)
   - `ai-news-frontend` (Node)
3. Set env vars:
   - Backend: `DATABASE_URL`, `INTERNAL_API_KEY`
   - Frontend: `NEXT_PUBLIC_API_BASE` (set to backend URL + `/v1`)
4. After deploy, run one pipeline cycle:
   - `POST /v1/internal/agents/run/all` with header `x-internal-api-key`.

## Option B: Vercel (frontend) + Render/Fly (backend)
1. Deploy backend first (Render/Fly/ECS).
2. Deploy `frontend/` on Vercel (root directory = `frontend`).
3. In Vercel Project Settings, add:
   - `NEXT_PUBLIC_API_BASE=https://<backend-domain>/v1`
4. Redeploy frontend.

## Production checklist
- Use managed Postgres (prefer pgvector-ready image).
- Restrict internal endpoints with strong `INTERNAL_API_KEY` and network rules.
- Schedule publish cadence every 10-15 minutes against `/v1/internal/agents/run/all`.
- Enable logs + error alerts for backend service and job failures.
