# Miraflores Workpaper

A web-native tax workpaper for the Okafor-Lindqvist 2025 return.
Rules and AI raise questions, people close them, and every action is recorded.

## Stack
- Postgres on Neon (`schema.sql`)
- FastAPI (`backend/app`), serving the API under `/api` and the built React app
- React + Tailwind via Vite (`frontend/`)
- One deployable service (`Dockerfile`)

## Layout
```
backend/app/       FastAPI app, database pool, encryption and masking
backend/loader/    loads the packet as delivered; maps lines to review areas
data/packet.json   the packet, unmodified (SHA-256 ee01f850...ad19)
data/findings_seed.json   findings from the offline review, with provenance
schema.sql         all 32 tables and the rules the database enforces
```

## First-time setup
```bash
# 1. Python deps
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 2. Environment
cp .env.example .env        # fill in both Neon URLs and a new ENCRYPTION_KEY

# 3. Tables (skip if already created in the Neon SQL editor)
psql "$DATABASE_URL_UNPOOLED" -f schema.sql

# 4. Load the packet (uses the DIRECT connection)
python -m backend.loader.load_packet data/packet.json --reset
#    Expect "All checks passed." with 74 documents, 3012 values, 627 v3 lines.

# 5. Frontend
cd frontend && npm install && npm run build && cd ..
```

## Run locally
```bash
uvicorn backend.app.main:app --reload --port 8000     # http://localhost:8000
# For frontend hot reload, also run:  cd frontend && npm run dev   (proxies /api)
```

## Deploy (Render or Railway)
- New web service from this repo, using the `Dockerfile`.
- Environment variables: `DATABASE_URL` (pooled) and `ENCRYPTION_KEY`
  (the same key used when loading, or encrypted values cannot be read).
- Health check path: `/api/health`.
