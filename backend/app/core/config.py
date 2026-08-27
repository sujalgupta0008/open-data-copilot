import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./opendatacopilot.db"
    JWT_SECRET: str = "dev-secret-change-me-please-32-chars-long!!"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080
    AI_PROVIDER: str = "mock"
    AI_API_KEY: str = ""
    AI_MODEL: str = "gpt-4o-mini"
    AI_BASE_URL: str = ""
    # Gemini-specific (fallback to AI_API_KEY/AI_MODEL if not set)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = ""
    GEMINI_BASE_URL: str = ""
    # Groq primary + fallback (Groq is now primary; Gemini removed)
    # PERFORMANCE: default to fast 8b-instant model for sub-3s Copilot latency (was 70b ~15s)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1/chat/completions"
    # Groq fallback — second model/key (primary → fallback → deterministic) — also fast 8b variant
    GROQ_FALLBACK_API_KEY: str = ""
    GROQ_FALLBACK_MODEL: str = "llama3-8b-8192"
    GROQ_FALLBACK_BASE_URL: str = ""
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    STORAGE_PATH: str = "./storage"
    PORT: int = 8000
    # Google Drive BYOS — Bring Your Own Storage
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"
    GOOGLE_DRIVE_FOLDER_NAME: str = "Open_Data_Copilot_Workspace"
    GOOGLE_OAUTH_SCOPE: str = "https://www.googleapis.com/auth/drive.file"
    DRIVE_MOCK_ENABLED: str = "1"  # 1 = mock filesystem drive for local/dev/tests, 0 = real Google API
    # Temporary pipeline — /tmp base (falls back to system temp)
    TMP_DIR: str = ""  # if empty, uses tempfile.gettempdir() / or ./storage/tmp

    @property
    def gemini_api_key(self) -> str:
        return (self.GEMINI_API_KEY or self.AI_API_KEY or "").strip()

    @property
    def gemini_model(self) -> str:
        return (self.GEMINI_MODEL or self.AI_MODEL or "gemini-1.5-flash").strip()

    @property
    def gemini_base_url(self) -> str:
        return (self.GEMINI_BASE_URL or self.AI_BASE_URL or "").strip()

    @property
    def groq_api_key(self) -> str:
        return (self.GROQ_API_KEY or "").strip()

    @property
    def groq_model(self) -> str:
        return (self.GROQ_MODEL or "llama-3.1-8b-instant").strip()

    @property
    def groq_base_url(self) -> str:
        return (self.GROQ_BASE_URL or "https://api.groq.com/openai/v1/chat/completions").strip()

    @property
    def groq_fallback_api_key(self) -> str:
        # Falls back to primary key if fallback key not set (single-key dual-model setup)
        return (self.GROQ_FALLBACK_API_KEY or self.GROQ_API_KEY or "").strip()

    @property
    def groq_fallback_model(self) -> str:
        return (self.GROQ_FALLBACK_MODEL or "llama3-8b-8192").strip()

    @property
    def groq_fallback_base_url(self) -> str:
        return (self.GROQ_FALLBACK_BASE_URL or self.GROQ_BASE_URL or "https://api.groq.com/openai/v1/chat/completions").strip()

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

settings = Settings()

# C7: fail-closed on default JWT secret — must be overridden in production via env / .env
_DEFAULT_JWT_SECRET = "dev-secret-change-me-please-32-chars-long!!"
if settings.JWT_SECRET == _DEFAULT_JWT_SECRET:
    # Fail-closed per C7: raise on startup if still the dev default.
    # Bypass only for tests (PYTEST_CURRENT_TEST) or explicit local dev opt-in ALLOW_DEV_JWT=1 so existing tests keep passing.
    if os.getenv("PYTEST_CURRENT_TEST") is None and os.getenv("ALLOW_DEV_JWT") not in ("1", "true", "True"):
        raise RuntimeError(
            "JWT_SECRET is set to the default dev value — set a secure random JWT_SECRET in env/.env (app/core/config.py:6)"
        )
