<div align="center">

# Open Data Copilot
### Premium AI Data Intelligence Workspace

*Clean, validate, analyze, explain and transform messy data into trustworthy insights*

**Upload → Diagnose → Clean → Validate → Explore → Ask → Analyze → Verify → Simulate → Report**

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)](backend/)
[![Node 20](https://img.shields.io/badge/Node-20-339933?style=flat&logo=node.js&logoColor=white)](frontend/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?style=flat&logo=fastapi&logoColor=white)](backend/app/main.py)
[![React 18](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react&logoColor=black)](frontend/)
[![Tests](https://img.shields.io/badge/tests-251%20passed-brightgreen?style=flat)](backend/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat)](LICENSE)
[![Groq](https://img.shields.io/badge/AI-Groq%20%7C%20Deterministic-orange?style=flat)](backend/app/ai/provider.py)

[Features](#features) • [Quick Start](#quick-start) • [Architecture](#architecture) • [API](#api) • [Deployment](#deployment)

</div>

---

## Overview

Open Data Copilot is a production-grade SaaS platform for data teams. It preserves core capabilities — Auth, Datasets, Profiling, Quality Scoring, SQL/DuckDB, Python execution, AI abstraction, Charts, History and Reports — and adds a premium workspace with reversible cleaning, lineage, evidence-based trust and BYOS storage.

> Deterministic by default. Every insight is backed by executed SQL, evidence tables and a trust score — LLMs explain, they do not fabricate.

---

## Features

| Area | Capabilities |
|------|--------------|
| **Cleaning Studio** `/datasets/:id/clean` | Manual (missing, dedup, column ops, text, numeric, date, row filter) + **AI Clean** — recommended plan, preview before apply |
| **AI Data Doctor** | Severity `Critical > Warning > Attention > Healthy` with Problem / Why / Recommendation / Preview / Apply |
| **Versioning & History** | `v1 → v2 → v3` in `storage/<user>/<dataset>/v<NUM>` + `dataset_versions`; full `transformations` log with Undo/Redo; Before/After diff |
| **Recipe & Lineage** | Save recipe, apply to compatible datasets, export JSON; lineage `File → Version → Transform → Analysis → Chart → Report` |
| **Evidence & Trust** | Insight + Evidence + Method + Executable SQL + Quality; **Trust Score 0–100** from completeness, sample size, duplicates, outliers; **Challenge Mode** |
| **EDA & Anomalies** | Auto EDA 5–8 insights; Anomaly Detective (outliers, rare categories, spikes, impossible values) |
| **Type Detection** | Schema/stats based: E-commerce, Flight Pricing, Finance, Marketing, HR, Generic |
| **Copilot** | Schema-aware prompts, conversational context, correct `AVG/SUM/COUNT/MIN/MAX/MEDIAN` mapping, 60s/90s timeout handling, large-set sampling |
| **What-If & Templates** | Scenario analysis (`price +10%`); industry templates filtered by detected type; Executive/Analyst mode |
| **Export** | Cleaned CSV/XLSX/JSON, SQL/Python, recipe, Power BI (normalized + Power Query M stub) |
| **Privacy Center** | `/privacy` — schema + 3 rows max to LLM (Groq), `mock` = no external call, keys never exposed |
| **BYOS** | Google Drive `drive.file` — real OAuth + mock `storage/drive/<user>/Open_Data_Copilot_Workspace`; streaming Drive + `/tmp` → `os.remove` (zero leftover) |
| **Dashboard** | Health, quality, recent activity; workspace tabs `Overview • Profile • Clean • Explore • Copilot • Insights • Lineage • Versions • Reports` |

---

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| **Frontend** | React 18, TypeScript, Vite 5, Tailwind CSS, React Router 6, TanStack Query 5, Recharts, Axios |
| **Backend** | FastAPI, Pydantic v2 (`ConfigDict`), SQLAlchemy, Pandas, NumPy, DuckDB, python-jose, passlib `bcrypt==4.0.1`, Httpx, APScheduler |
| **Database** | PostgreSQL 15 (Docker) or SQLite (`sqlite:///./opendatacopilot.db`) |
| **Storage** | Local filesystem + versioned copies + mock Drive |
| **AI** | `groq` → `llama-3.1-8b-instant` (primary, ~0.8s) → `llama3-8b-8192` (fallback) → deterministic |

---

## Architecture

```
Client (Vite) ──► FastAPI (lifespan) ──► 15 Routers ──► Services
                                     ├─ auth, datasets, analysis, reports, dashboard
                                     ├─ cleaning, intelligence, metrics, monitors
                                     ├─ workflow, planning, driver, privacy, ai
                                     └─ google_drive (BYOS)
                          ├─ DuckDB (in-memory SQL)  ├─ Profiler (sampling)
                          ├─ Python AST sandbox      └─ Report Pipeline (single source of truth)
```

**Key modules:** `data_engine/cleaning.py`, `profiler.py` (robust datetime with sampling), `intelligence.py`, `report_pipeline.py`, `execution/sql.py` (SELECT/WITH allowlist), `execution/python_exec.py` (AST block).

---

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py              # lifespan, 15 routers
│   │   ├── core/                # config (SettingsConfigDict), security (JWT), deps
│   │   ├── ai/provider.py       # groq → fallback → deterministic
│   │   ├── data_engine/         # cleaning, profiler, intelligence, report_pipeline
│   │   ├── execution/           # sql (DuckDB), python_exec (sandbox)
│   │   ├── api/                 # all routers
│   │   ├── models/ schemas/ services/
│   │   └── scheduler.py
│   ├── tests/                   # 27 files, 251 tests
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/               # Dashboard, Datasets, Copilot, CleaningStudio, Reports, Settings
│   │   ├── components/          # ui, charts, copilot, layout
│   │   ├── hooks/useAuth.tsx
│   │   └── services/api.ts      # 60s default, 90s for analyze
│   ├── vite.config.ts
│   └── package.json
├── storage/                     # gitignored, .gitkeep
├── sample_data/                 # ecommerce.csv, flight_price.csv
├── docker-compose.yml
├── pytest.ini
└── .env.example
```

---

## Quick Start

### Prerequisites
Node 20+, Python 3.11+, Docker (optional)

### 1. Environment
```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
# Edit .env — see Configuration below
```

### 2. Backend
```bash
cd backend
pip install -r requirements.txt
# optional real Drive: pip install google-api-python-client google-auth google-auth-oauthlib
uvicorn app.main:app --reload --port 8000
# http://localhost:8000/health  http://localhost:8000/docs
```

### 3. Frontend
```bash
cd frontend
npm install
npm run dev      # http://localhost:5173  (proxies /api → 8000)
npm run build    # production
npm run typecheck && npm run lint
```

### 4. Docker (full stack)
```bash
docker-compose up --build
# frontend http://localhost:5173  backend http://localhost:8000  db :5432
```

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Postgres or SQLite | `sqlite:///./opendatacopilot.db` |
| `JWT_SECRET` | Min 32 chars, fail-closed | `dev-secret...` |
| `AI_PROVIDER` | `groq` \| `mock` | `mock` |
| `GROQ_API_KEY` | Primary (llama-3.1-8b-instant) | — |
| `GROQ_FALLBACK_API_KEY` | Secondary (llama3-8b-8192) | — |
| `CORS_ORIGINS` | Allowed origins | `http://localhost:5173,http://localhost:3000` |
| `STORAGE_PATH` | Local storage root | `./storage` |
| `GOOGLE_CLIENT_ID/SECRET` | BYOS real Drive | — |
| `GOOGLE_REDIRECT_URI` | Must match Google Console | `http://localhost:8000/api/auth/google/callback` |
| `DRIVE_MOCK_ENABLED` | `1` mock (local) / `0` real | `1` |
| `VITE_API_URL` | Frontend → Backend URL | `http://localhost:8000` (empty = proxy) |

Generate secret: `openssl rand -hex 32`

---

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/register, /login, /me` | Auth + JWT |
| `POST` | `/api/datasets/upload` | CSV/XLSX/Parquet (**5GB BYOS**, `MAX_UPLOAD_SIZE_BYTES`) |
| `GET` | `/api/datasets/:id/profile, /preview, /diff, /lineage` | Profile, diff, lineage |
| `POST` | `/api/datasets/:id/clean/preview, /apply` | Cleaning |
| `GET` | `/api/datasets/:id/type, /eda, /anomalies` | Intelligence |
| `POST` | `/api/datasets/:id/analyze` | Copilot (Groq → DuckDB → Trust → Chart) |
| `POST` | `/api/datasets/:id/trust-score, /challenge, /whatif` | Verification |
| `POST` | `/api/reports, /reports/from-session` | Single & combined reports |
| `GET` | `/api/drive/workspace, /files, /verify` | BYOS |
| `GET` | `/api/privacy` | Privacy disclosure |

Full spec: `http://localhost:8000/docs`

---

## Testing

```bash
pytest -q                         # backend — 251 passed
python scripts/e2e.py             # upload → profile → copilot → history → report → delete
npm run typecheck --prefix frontend
npm run lint --prefix frontend    # --max-warnings 0
npm run build --prefix frontend   # 2403 modules
```

Verified: Auth isolation (404), SQL allowlist, Python sandbox, aggregation intents, cleaning lifecycle, Groq fallback, BYOS tmp cleanup, statistical correctness.

---

## Deployment

**Production env:**
- `DATABASE_URL` → Neon / Supabase / RDS
- `JWT_SECRET` → strong random
- `CORS_ORIGINS` → `https://yourdomain.com`
- `STORAGE_PATH` → persistent volume
- `GOOGLE_REDIRECT_URI` → `https://api.yourdomain.com/api/auth/google/callback` (whitelist in Google Console)
- `VITE_API_URL` → `https://api.yourdomain.com`

```bash
docker-compose up --build -d
# or: backend → Fly.io/Render, frontend dist → Vercel, db → Neon
```

Health checks: `GET /health`, `GET /api/ai/status` (provider, model, fallback)

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `Google login` on Login page fails | Button is **Drive linking**, not user auth | First email signup → `Settings → Bring Your Own Storage → Connect Google Drive (Mock)` |
| `redirect_uri_mismatch` | URI not whitelisted | Add `GOOGLE_REDIRECT_URI` to Google Cloud Console → Authorized redirect URIs |
| `timeout of 30000ms` | Large dataset profiling | Fixed: 60s default + 90s analyze + sampling (`profiler.py:54`); retry |
| `JWT_SECRET` error on startup | Default secret | Set strong `JWT_SECRET` in `.env` |

---

## Limitations

- Python execution is in-process sandbox (prod: isolated worker)
- Mock AI is heuristic; set `GROQ_API_KEY` for Groq
- Report PDF currently JSON via `reportlab` (PDF stub ready)
- 5GB upload limit (BYOS, configurable via `MAX_UPLOAD_SIZE_BYTES` in `core/config.py:31`)

---

## License

MIT — see [LICENSE](LICENSE)
