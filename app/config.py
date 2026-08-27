"""Application configuration, loaded from environment variables / a .env file.

Nothing secret is hardcoded here — every credential comes from the environment.
See `.env.example` for the full list of variables and their meaning.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core ---
    api_key: str = "changeme-generate-a-strong-key"
    provider: str = "mock"  # mock | fixture | linkedin
    database_url: str = "sqlite:///./data/profiles.db"
    cache_ttl_seconds: int = 604800  # 7 days
    log_level: str = "INFO"
    run_inline_worker: bool = True

    # --- Politeness / rate limiting (courtesy delay, NOT anti-detection) ---
    fetch_min_delay_seconds: float = 1.5
    fetch_max_delay_seconds: float = 4.0

    # --- LinkedIn scraper (only read when provider == "linkedin") ---
    li_email: str = ""
    li_password: str = ""
    session_state_path: str = "./session/state.json"
    linkedin_headless: bool = True

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sqlite_path(self) -> str:
        """Filesystem path parsed out of a sqlite:// DATABASE_URL."""
        url = self.database_url
        if ":///" in url:
            return url.split(":///", 1)[1]
        return url.split("://", 1)[-1]


@lru_cache
def get_settings() -> Settings:
    return Settings()
