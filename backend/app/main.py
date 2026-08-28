from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import init_db
from app.api import auth, datasets, analysis, reports, dashboard, cleaning, intelligence, privacy, ai, metrics, monitors, workflow, planning, driver
from app.api.reports import shared_router as shared_reports_router
from app.api.analysis import shared_analysis_router
from app.api import notifications
from app.api import google_drive as google_drive_api
from app.scheduler import start_scheduler, shutdown_scheduler
import os
import logging

logger = logging.getLogger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    os.makedirs(settings.STORAGE_PATH, exist_ok=True)
    init_db()
    try:
        start_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler failed to start: {e}")
    # .env validation on startup — Groq primary + fallback (Gemini deprecated)
    try:
        groq_key = (settings.groq_api_key or "").strip()
        groq_fallback_key = (settings.groq_fallback_api_key or "").strip()
        groq_model = settings.groq_model
        groq_fallback_model = settings.groq_fallback_model
        groq_base = settings.groq_base_url
        provider = (settings.AI_PROVIDER or "mock").strip().lower()
        if provider == "groq":
            if not groq_key:
                msg = "⚠️ GROQ_API_KEY not set — will skip Groq primary (llama-3.1-8b-instant)"
                logger.warning(msg)
                print(msg)
            else:
                logger.info(f"GROQ_API_KEY present (preview {groq_key[:4]}…{groq_key[-4:]}) — Groq primary enabled ({groq_model} @ {groq_base}) [fast 8b-instant ~0.8s]")
            if not groq_fallback_key and not groq_key:
                msg = "⚠️ GROQ_FALLBACK_API_KEY not set — will skip Groq fallback (llama3-8b-8192) — will use primary key as fallback if set"
                logger.warning(msg)
                print(msg)
            elif groq_fallback_key:
                logger.info(f"GROQ_FALLBACK_API_KEY present (preview {groq_fallback_key[:4]}…{groq_fallback_key[-4:]}) — Groq fallback enabled ({groq_fallback_model})")
            else:
                logger.info(f"GROQ fallback will reuse primary key — model {groq_fallback_model}")
        else:
            if not groq_key:
                msg = "⚠️ GROQ_API_KEY not set — Groq (llama/qwen) unavailable"
                logger.warning(msg)
                print(msg)
            else:
                logger.info(f"GROQ_API_KEY present (preview {groq_key[:4]}…{groq_key[-4:]}) — Groq enabled ({groq_model} → {groq_fallback_model})")
        gemini_key = (settings.gemini_api_key or "").strip()
        if gemini_key:
            msg = f"ℹ️ GEMINI_API_KEY still set (deprecated) — AI_PROVIDER is '{provider}', Gemini will not be used unless AI_PROVIDER=gemini"
            logger.info(msg)
            print(msg)
        if provider == "mock" or (not groq_key and not groq_fallback_key and not gemini_key):
            msg = "Heuristic mode: no LLM keys configured — deterministic analysis will be used"
            logger.warning(msg)
            print(msg)
    except Exception as _e:
        logger.warning(f"Startup key validation failed: {_e}")
        print(f"Startup key validation failed: {_e}")
    yield
    # --- shutdown ---
    try:
        shutdown_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler shutdown failed: {e}")


app = FastAPI(title="Open Data Copilot", version="1.0.0", lifespan=lifespan, redirect_slashes=False)

origins = settings.cors_origins_list
# Production: if CORS_ORIGINS is not explicitly set to prod frontend (Vercel/Render), allow all origins via regex
# to prevent 401/CORS block on email signup & Google OAuth. Bearer token does not require cookies, so wildcard is safe.
# Keep explicit origins for dev, but also allow any https origin (Vercel, Render) via regex fallback.
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_origin_regex=r"https://.*|http://localhost:.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Fix 308 redirect loop on trailing-slash mismatch:
# FastAPI/Starlette by default 307/308-redirects /path/ <-> /path depending on route definition.
# Frontend may call /api/auth/google/login or /api/auth/google/login/ interchangeably;
# axios then follows 308 but drops auth headers/body leading to subsequent 404.
# We normalize request path by stripping trailing slashes (except root) BEFORE routing,
# and disable automatic redirect_slashes so both variants resolve cleanly with 200.
# Also handles raw_path for Uvicorn/ASGI (bytes) to ensure real prod server matches.
@app.middleware("http")
async def normalize_trailing_slash(request: Request, call_next):
    # Only normalize API paths — leave static/docs untouched if needed; safe to normalize all
    path = request.scope.get("path", "")
    raw_path = request.scope.get("raw_path", b"")
    if path != "/" and path.endswith("/"):
        new_path = path.rstrip("/")
        request.scope["path"] = new_path
        # Also update raw_path (bytes) for ASGI servers that route on raw_path
        try:
            if isinstance(raw_path, (bytes, bytearray)) and raw_path.endswith(b"/"):
                request.scope["raw_path"] = raw_path.rstrip(b"/")
        except Exception:
            pass
    return await call_next(request)

app.include_router(auth.router)
app.include_router(datasets.router)
app.include_router(analysis.router)
app.include_router(reports.router)
app.include_router(shared_reports_router)
app.include_router(shared_analysis_router)
app.include_router(notifications.router)
app.include_router(dashboard.router)
app.include_router(cleaning.router)
app.include_router(intelligence.router)
app.include_router(metrics.router)
app.include_router(monitors.router)
app.include_router(workflow.router)
app.include_router(planning.router)
app.include_router(driver.router)
app.include_router(privacy.router)
app.include_router(ai.router)
# BYOS Google Drive — OAuth & Workspace (non-destructive middleware)
app.include_router(google_drive_api.router)
app.include_router(google_drive_api.drive_router)

@app.get("/")
def root():
    return {"message": "Open Data Copilot API", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok"}

# For local debugging
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
