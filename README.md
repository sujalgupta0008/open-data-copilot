# Open Data Copilot — Premium AI Data Intelligence Workspace

> **"An AI-powered data intelligence workspace that cleans, validates, analyzes, explains, and transforms messy data into trustworthy insights."**

Upload → **Diagnose** → Clean → Validate → Explore → Ask → **Analyze** → Verify → Simulate → Report

Production-quality SaaS upgrade preserving original Auth, Datasets, Profiling, Quality Scoring, SQL/DuckDB, Python, AI Abstraction, Copilot, Charts, History, Reports — plus BYOS, Groq AI, Monitors, Trust Engine.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue)](backend/) [![Node 20](https://img.shields.io/badge/node-20-green)](frontend/) [![FastAPI](https://img.shields.io/badge/FastAPI-0.110-teal)](backend/app/main.py) [![React 18](https://img.shields.io/badge/React-18-61dafb)](frontend/) [![Tests 251](https://img.shields.io/badge/tests-251%20passed-brightgreen)](backend/tests/)

---

## ✨ Premium Features

### Data Cleaning Studio — `/datasets/:id/clean`
**Manual Mode** (preview-before-apply):
- **Missing**: drop, fill mean/median/mode, ffill/bfill, custom value
- **Duplicates**: detect → preview → remove
- **Column Ops**: rename, remove, reorder, change dtype (int/float/string/datetime/numeric)
- **Text**: trim, lower/upper/title, find & replace, standardize
- **Numeric**: to_numeric, outlier winsorize/remove/flag
- **Date**: detect text-dates, to_datetime, standardize, invalid detection
- **Row Filter**: by value / numeric range / date

**AI Mode — `Clean with AI`**: generates `Recommended Cleaning Plan` (e.g., Remove 127 duplicates → Standardize Airline → Convert Price → Parse Date → Fill Duration → Flag outliers) → Review → Apply all / selected / preview each.

### AI Data Doctor
Auto-analyzes after upload with severity:
| Severity | Meaning |
|----------|---------|
| **Critical** | >20% missing, high duplicates, impossible values |
| **Warning** | 5–20% missing, case inconsistencies, date-as-text |
| **Attention** | <5% missing, whitespace, rare categories |
| **Healthy** | No major issues |
Each issue shows **Problem / Why it matters / Recommendation / Preview / Apply / Reject** — never silent.

### Reversible Cleaning & Transformation History
```
Original → Remove duplicates → Standardize Airline → Convert Price → Current
```
Every op recorded in `transformations` (`undone` flag) with **Undo / Redo**, original file never overwritten.

### Dataset Versioning
```
v1 Original → v2 Duplicates removed → v3 Missing handled → v4 Final cleaned
```
Stored `storage/<user_id>/<dataset_id>/v<NUM>.<ext>` + `dataset_versions` (`is_current` pointer) — view / compare / restore / rename.

### Before / After Data Diff
Delta in rows, cols, missing, duplicates, dtypes, unique counts, quality score.
```
BEFORE: 10,683 rows, 127 dup, 1,284 missing, " IndiGo " → AFTER: 10,556 rows, 0 dup, "IndiGo"
```
`GET /api/datasets/:id/diff?from_version=1&to_version=4`

### Cleaning Recipe
Auto-recorded → **Save Recipe** (“Flight Standardization”) → apply to compatible dataset (column check, preview) → export JSON.
`GET /api/datasets/:id/export/recipe`

### Data Lineage
`Original File → Version → Transformation → Clean Dataset → Analysis → SQL/Python → Result → Chart → Insight → Report`
`GET /api/datasets/:id/lineage` answers “Where did this insight come from?”

### Insight Evidence & Trust
Every insight: **Insight / Evidence / Method / Query (executable SQL) / Data Quality**. Deterministic via DuckDB.

**Trust Score 0–100** (evidence-based, NOT LLM confidence) from completeness, sample size, duplicate rate, outlier impact, execution success. `POST /api/datasets/:id/trust-score`

**Challenge Mode** `POST /api/datasets/:id/challenge` → Original / Challenge / Evidence / Conclusion.

### Automatic EDA
After cleaning, **5–8 high-value analyses**: distributions, correlations, missingness, categorical dominance, trends, outliers. `GET /api/datasets/:id/eda`

### Anomaly Detective
Outliers, rare categories, spikes, impossible values. `GET /api/datasets/:id/anomalies` + `POST .../investigate`

### Dataset Type Detection (schema/statistics, not filename)
E-commerce, Flight Pricing, Finance, Marketing, HR, Generic — `GET /api/datasets/:id/type`

### Dataset-Aware Copilot
Prompts generated from actual schema + type (Flight: airline price, route outliers; E-commerce: revenue by category, etc.). Remembers dataset, history, filters. Correctly maps `average→AVG()`, `total→SUM()`, `count→COUNT()`, `min→MIN()`, `max→MAX()`, `median→MEDIAN()`.

**Performance:** Frontend `api.ts:6` default `60000ms`, analyze `Copilot.tsx:248` `90000ms`; backend `profiler.py:54` samples large series (>2000 rows → 1000-row probe, skips element-wise fallback) — fixes historical_data 30s timeout; `report_pipeline.py:19` caches profile for data-quality audits.

### What-If Analysis
`POST /api/datasets/:id/whatif` `{column, percent, type}` — “What if price +10%?” → Actual vs Scenario vs Diff vs % Change. Labeled **Scenario Analysis**.

### Industry Templates
`GET /api/templates?dataset_type=Flight Pricing` — only compatible templates shown.

### Executive / Analyst Mode
Same analysis, different presentation. Analyst: SQL, methodology; Executive: KPIs, trends, risks.

### Export
Cleaned dataset CSV/XLSX/JSON, original, SQL/Python, charts, cleaning recipe, quality report, Power BI (normalized cols + Power Query M stub). `GET /api/datasets/:id/export?format=...`

### Privacy Center — `/privacy`
Explains schema-only vs samples vs no full rows to LLM. `mock` = no call; `groq` = schema + 3 rows max. `GET /api/privacy`

### Premium SaaS UI
Linear + Vercel + Analytics style — subtle borders, professional tables, Recharts, dark/light, `prefers-reduced-motion`.

### Premium Dashboard & Workspace
Dashboard: datasets, analyses, reports, avg quality, health, recent activity. Workspace tabs: **Overview • Profile • Clean • Explore • Copilot • Insights • Lineage • Versions • Reports**.

### BYOS — Bring Your Own Storage (Google Drive `drive.file`)
- `GET /api/auth/google/login` → `https://accounts.google.com/o/oauth2/v2/auth` (real consent)
- `GET /api/auth/google/callback` → auto-creates `Open_Data_Copilot_Workspace` folder, redirects `settings?status=success`
- `POST /api/auth/google/mock-login` (Bearer token) — instant mock for dev/tests when `DRIVE_MOCK_ENABLED=1`
- `GET /api/drive/workspace`, `/files`, `/verify` — mock uses `storage/drive/<user_id>/Open_Data_Copilot_Workspace`
- Middleware streams uploads to Drive + `/tmp` during analysis → results to Drive → `os.remove` → zero leftover (verified `test_byos_e2e.py:test_4_zero_tmp_leftover`).
- **Login page Google button is Drive linking, NOT user auth.** First do email signup/login, then `Settings → Bring Your Own Storage → Connect Google Drive (Mock)`.

### Data Monitors & History
- Past sessions, lineage visualization, alert triggers (`test_monitor_alerts.py`, `test_intelligence_layers.py`).

---

## Architecture

- **Frontend**: React 18, TypeScript, Vite 5, Tailwind, React Router 6, TanStack Query 5, Recharts, axios
- **Backend**: FastAPI, Pydantic v2 (`ConfigDict`), SQLAlchemy, Pandas, NumPy, DuckDB, python-jose, passlib[bcrypt 4.0.1], httpx, SQLAlchemy, openpyxl/pyarrow, apscheduler
- **DB**: PostgreSQL 15 (Docker) or SQLite (`DATABASE_URL=sqlite:///./opendatacopilot.db`)
- **Storage**: `storage/<user_id>/<dataset_id>.<ext>` + versioned `storage/<user_id>/<dataset_id>/v<NUM>.<ext>` + mock Drive `storage/drive/<user_id>/Open_Data_Copilot_Workspace`
- **AI**: `app/ai/provider.py` — `AI_PROVIDER=groq|mock`, Groq `llama-3.1-8b-instant` (primary, ~0.8s) → `llama3-8b-8192` (fallback) → deterministic

**Routers (`app/main.py:5` lifespan):**
`auth, datasets, analysis, reports (+shared), notifications, dashboard, cleaning, intelligence, metrics, monitors, workflow, planning, driver, privacy, ai, google_drive`

**New Tables:** `dataset_versions`, `transformations`, `cleaning_recipes`, `analysis_sessions/messages/results/charts`, `metrics`, `monitors`

**Key Modules:**
- `app/data_engine/cleaning.py` — manual ops + preview + diff
- `app/data_engine/intelligence.py` — type, doctor, EDA, anomalies, trust, challenge, what-if, lineage
- `app/data_engine/profiler.py:54` — robust_datetime_parse with sampling (large-set fix)
- `app/data_engine/report_pipeline.py:243` — single source of truth pipeline (copilot + reports)
- `app/execution/sql.py` — validate (only SELECT/WITH) + DuckDB in-memory view
- `app/execution/python_exec.py` — AST sandbox (blocks `__class__`, `__subclasses__`, `os/sys`)

---

## Folder Structure
```
.
├── backend/
│   ├── app/
│   │   ├── main.py           # lifespan (replaces on_event), 15 routers
│   │   ├── core/config.py    # SettingsConfigDict, groq primary/fallback
│   │   ├── core/security.py  # bcrypt + JWT
│   │   ├── ai/provider.py    # groq → groq-fallback → deterministic, MockProvider
│   │   ├── data_engine/      # cleaning.py, profiler.py, intelligence.py, report_pipeline.py
│   │   ├── execution/        # sql.py, python_exec.py
│   │   ├── api/              # auth, datasets, analysis, cleaning, intelligence, reports, planning, google_drive, etc.
│   │   └── models/models.py
│   ├── tests/                # 27 files, 251 tests
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/            # Dashboard, Datasets, DatasetDetail, Copilot, CleaningStudio, Reports, Settings, PrivacyCenter
│   │   ├── components/       # ui/*, charts/ChartRenderer, copilot/*, layout/Sidebar
│   │   ├── hooks/useAuth.tsx # login/signup/logout + /me
│   │   └── services/api.ts   # axios 60s default, 90s for analyze
│   ├── vite.config.ts        # chunkSizeWarningLimit 800 + manualChunks vendor
│   ├── package.json
│   └── Dockerfile
├── storage/                  # .gitkeep (gitignored contents)
├── sample_data/              # ecommerce.csv, flight_price.csv
├── scripts/e2e.py            # portable pathlib path
├── database/.gitkeep
├── docker-compose.yml
├── pytest.ini                # filterwarnings (DeprecationWarning)
├── .env.example
└── README.md
```

---

## Setup

### Prereqs
Node 20+, Python 3.11+, Docker (optional for Postgres)

### Environment
```bash
cp .env.example .env
# Edit .env:
# DATABASE_URL=sqlite:///./opendatacopilot.db  # local
# DATABASE_URL=postgresql://postgres:postgres@localhost:5432/opendatacopilot
# JWT_SECRET=openssl rand -hex 32  (min 32 chars, fail-closed in config.py:87)
# AI_PROVIDER=groq  # or mock for offline deterministic
# GROQ_API_KEY=gsk_... (primary, llama-3.1-8b-instant)
# GROQ_FALLBACK_API_KEY=gsk_... (optional, falls back to primary key)
# CORS_ORIGINS=http://localhost:5173,http://localhost:3000
# STORAGE_PATH=./storage
# GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI=http://localhost:8000/api/auth/google/callback
# DRIVE_MOCK_ENABLED=1 (1=mock local drive, 0=real Google API + google-api packages)
# TMP_DIR= (empty → system temp)
```

Frontend env:
```bash
cp frontend/.env.example frontend/.env
# VITE_API_URL=http://localhost:8000  # leave empty to use vite proxy
```

### Backend
```bash
cd backend
pip install -r requirements.txt
# Optional for real Drive: pip install google-api-python-client google-auth google-auth-oauthlib
uvicorn app.main:app --reload --port 8000
# health: http://localhost:8000/health  docs: http://localhost:8000/docs
```

### Frontend
```bash
cd frontend
npm install
npm run dev     # http://localhost:5173 (proxies /api → 8000)
npm run build   # tsc + vite build (chunk 800k limit)
npm run typecheck
npm run lint
```

### Docker
```bash
docker-compose up --build
# backend: http://localhost:8000  frontend: http://localhost:5173  db: 5432
```

---

## Testing

```bash
cd backend
pytest -q                      # 251 passed (pytest.ini filters DeprecationWarning)
python scripts/e2e.py          # custom e2e via requests (uses pathlib for csv)
```

**Verify:**
```bash
python -m pytest backend/tests -v          # 251 passed, 0 warnings
npm run typecheck --prefix frontend        # 0 errors
npm run lint --prefix frontend             # 0 warnings (--max-warnings 0)
npm run build --prefix frontend            # ✓ 2403 modules, no chunk warning
```

**Coverage:** Auth, ownership (404 cross-user), SQL allowlist (block DROP/DELETE/;), Python AST sandbox (blocks `__class__.__subclasses__`), aggregation intents (AVG/SUM/COUNT/MIN/MAX/MEDIAN), cleaning (missing/dedup/type/text/date/outlier/undo/redo/diff/version/doctor), AI fallback (Groq primary → fallback → deterministic), BYOS (workspace, tmp zero leftover), data-quality isolation/audit, statistical correctness (Welch, χ², Wilson), monitors, reporting (single/combined PDF).

---

## E2E Workflow Verified
1. Register/Login → 2. Upload (CSV/XLSX/Parquet) → 3. Type detection → 4. Doctor → 5. Review → 6. Preview→Apply → 7. Diff → 8. Undo/Redo → 9. Version → 10. EDA → 11. Copilot “Which airline has highest average price?” → 12. Verify AVG → 13. Chart → 14. Challenge → 15. Anomaly → 16. What-if → 17. Lineage → 18. Report → 19. Download cleaned CSV/recipe → 20. Original unchanged → 21. BYOS verify write/read → 22. Auth isolation

---

## Security
- bcrypt (`passlib[bcrypt]==4.0.1`), JWT bearer, ownership 404, SQL allowlist (only `SELECT`/`WITH`, blocks `DROP/DELETE/UPDATE/INSERT/;` and `read_csv/read_parquet` file leaks), Python AST sandbox (blocks `os`, `sys`, `socket`, `__class__`), CORS, no secrets to frontend, file 50MB allowlist, rate limiting where practical.

---

## Deployment

**Env for prod:**
- `DATABASE_URL` → managed Postgres (Neon/Supabase/RDS)
- `JWT_SECRET` → `openssl rand -hex 32`
- `CORS_ORIGINS` → `https://yourdomain.com`
- `STORAGE_PATH` → persistent volume (`/app/storage` in Docker)
- `GROQ_API_KEY`/`GROQ_FALLBACK_API_KEY`
- `GOOGLE_REDIRECT_URI=https://api.yourdomain.com/api/auth/google/callback` (add to Google Cloud Console → Authorized redirect URIs) + `DRIVE_MOCK_ENABLED=0` for real Drive
- `VITE_API_URL=https://api.yourdomain.com` in frontend build

**Docker prod:**
```bash
docker-compose up --build -d
# or separate: backend image → Fly.io/Render, frontend dist → Vercel, db → Neon
```

---

## Troubleshooting

- **Login nahi ho raha / Google login fail:** Login page ka “Sign in with Google” Drive linking hai, user auth nahi. Pehle email signup → fir `Settings → Bring Your Own Storage → Connect Google Drive (Mock)` (`mock-login` needs Bearer token). Real Google OAuth ke liye `GOOGLE_REDIRECT_URI` Google Console me whitelist karo.
- **Copilot `timeout of 30000ms` (Image 1):** Fixed to `60s` default + `90s` for analyze (`api.ts:6`, `Copilot.tsx:248`). Large datasets now sampled (`profiler.py:54` 2000→1000 probe) + profile cached (`report_pipeline.py:19`), retry se success.
- **Storage not found / database locked:** Check `STORAGE_PATH` exists, Docker volume mounted, `DATABASE_URL` correct.

---

## Known Limitations
- Python execution in-process sandbox (prod: isolated worker)
- Mock AI is heuristic; set `GROQ_API_KEY` for real LLM (auto-fallback to deterministic if both groq fail)
- Report PDF is JSON download (PDF via `reportlab` can be added)
- 50MB upload limit (configurable `app/api/datasets.py`)

---

## License
MIT
