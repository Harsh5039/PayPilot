"""Runtime configuration. Everything is env-driven so nothing is hardcoded."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass


ROOT = Path(__file__).resolve().parent.parent


class Settings:
    def __init__(self) -> None:
        self.sarvam_api_key: str = os.getenv("SARVAM_API_KEY", "").strip()
        self.sarvam_base_url: str = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai/v1").rstrip("/")
        self.sarvam_model: str = os.getenv("SARVAM_MODEL", "sarvam-105b")
        self.sarvam_timeout: float = float(os.getenv("SARVAM_TIMEOUT", "20"))
        raw_db = os.getenv("DATABASE_PATH", "paypilot.db")
        # A relative path is resolved against the project root, not the process
        # CWD, so the same file is found whether uvicorn starts from the repo,
        # from /app in a container, or from a systemd unit somewhere else.
        db_path = Path(raw_db)
        self.database_path: str = str(db_path if db_path.is_absolute() else ROOT / db_path)
        self.consent_ttl_days: int = int(os.getenv("CONSENT_TTL_DAYS", "30"))
        self.demo_mode: bool = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")
        self.cors_origins: list[str] = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.sarvam_api_key)

    @property
    def llm_label(self) -> str:
        return self.sarvam_model if self.llm_enabled else "offline-rule-agent"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
