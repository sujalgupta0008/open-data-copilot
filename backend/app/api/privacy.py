from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/api", tags=["privacy"])

@router.get("/privacy")
def get_privacy():
    provider = settings.AI_PROVIDER
    # describe what is sent
    if provider == "mock":
        detail = {
            "ai_processing": "Mock provider runs locally; no data sent externally.",
            "what_is_sent": "No external API call. All analysis is deterministic heuristics using schema summaries.",
            "raw_rows_sent": False,
            "schema_sent": False,
            "sample_rows_sent": False
        }
    elif provider == "openai":
        detail = {
            "ai_processing": f"AI provider is {provider} ({settings.AI_MODEL}). When you ask a question, we send schema summaries, aggregated statistics, and optionally 3 sample rows - never the full dataset - to the configured LLM.",
            "what_is_sent": "Schema (column names/types), row/column counts, up to 3 sample rows, and your question. Full raw dataset is never sent.",
            "raw_rows_sent": False,
            "schema_sent": True,
            "sample_rows_sent": True,
            "aggregated_stats_sent": True,
            "full_dataset_sent": False,
            "endpoint": settings.AI_BASE_URL or "https://api.openai.com/v1/chat/completions",
            "model": settings.AI_MODEL
        }
    elif provider == "gemini":
        # Show both Gemini primary and Groq fallback in privacy
        groq_configured = bool(settings.groq_api_key)
        fallback_note = " If Gemini rate-limits or fails, Groq (fallback LLM) is tried automatically before deterministic analysis; same minimal context (schema, 3 sample rows, result sample) may be sent to Groq. Full raw dataset is never sent to either provider."
        detail = {
            "ai_processing": f"Gemini primary ({settings.gemini_model}) with Groq fallback ({settings.groq_model}) — LLM explains DuckDB results. Deterministic remains numerical source of truth." + fallback_note,
            "what_is_sent": "Schema (column names/types), row/column counts, up to 3 sample rows, your question, and 5-row result sample for grounding. Full raw dataset is never sent to Gemini or Groq. Groq receives same minimal context only on Gemini failure.",
            "raw_rows_sent": False,
            "schema_sent": True,
            "sample_rows_sent": True,
            "aggregated_stats_sent": True,
            "full_dataset_sent": False,
            "endpoint": settings.gemini_base_url or f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            "model": settings.gemini_model,
            "groq_model": settings.groq_model if groq_configured else None,
            "groq_endpoint": settings.groq_base_url if groq_configured else None,
            "providers": ["gemini", "groq", "deterministic"]
        }
    elif provider == "ollama":
        detail = {
            "ai_processing": f"Ollama local provider ({settings.AI_MODEL}) at {settings.AI_BASE_URL or 'http://localhost:11434'}. Runs locally, no cloud data sent. Failures fall back silently to deterministic.",
            "what_is_sent": "Schema and sample rows stay on local Ollama instance; no external cloud call. Full dataset never sent externally.",
            "raw_rows_sent": False,
            "schema_sent": True,
            "sample_rows_sent": True,
            "full_dataset_sent": False,
            "endpoint": settings.AI_BASE_URL or "http://localhost:11434",
            "model": settings.AI_MODEL
        }
    else:
        detail = {
            "ai_processing": f"Provider {provider} - check configuration.",
            "what_is_sent": "Schema-only where possible.",
            "raw_rows_sent": False
        }
    return {
        "privacy_center": detail,
        "data_isolation": "All datasets are isolated per user; ownership checks on every endpoint.",
        "file_validation": "Only CSV/XLSX/JSON/Parquet, 5GB limit (BYOS), validated on upload.",
        "sql_sandbox": "Only SELECT/WITH allowed; DuckDB in-memory.",
        "python_sandbox": "Restricted globals, blocked os/sys/socket.",
        "secrets": "API keys stored server-side only, never exposed to frontend."
    }

@router.get("/templates")
def get_templates(dataset_type: str = None):
    templates = {
        "E-commerce": ["Revenue by category", "Top products by revenue", "Average order value", "Monthly revenue trend", "Customer retention", "Category performance"],
        "Flight Pricing": ["Fare by airline", "Route performance", "Source vs destination", "Duration analysis", "Stops impact", "Price distribution"],
        "Finance": ["Revenue trend", "Margin analysis", "Growth variance", "Expense breakdown"],
        "Marketing": ["CTR by campaign", "Conversion funnel", "Acquisition channels", "Campaign ROI"],
        "HR": ["Attrition by department", "Tenure distribution", "Compensation analysis", "Headcount trends"],
        "Generic Tabular Dataset": ["Distribution overview", "Correlation analysis", "Missing values", "Outlier detection"]
    }
    if dataset_type and dataset_type in templates:
        return {"dataset_type": dataset_type, "templates": templates[dataset_type]}
    return {"templates": templates}
