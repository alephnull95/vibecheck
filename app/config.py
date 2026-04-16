"""
config.py – Central settings for VibeCheck.

All values are loaded from environment variables (or a .env file).
Copy .env.example to .env and fill in your keys before starting.
"""

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Primary source: os env vars (Portainer) always win.
        # Secondary source: /config/settings.env written by the /setup UI,
        # persisted on a Docker named volume (vibecheck_config).
        env_file="/config/settings.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────
    app_env: Literal["development", "production", "test"] = "development"
    secret_key: str = Field(..., min_length=16)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── PostgreSQL ───────────────────────────────────
    database_url: str  # postgresql+psycopg2://user:pass@host:port/db

    # ── Redis / Celery ───────────────────────────────
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # ── Radarr ───────────────────────────────────────
    radarr_url: Optional[str] = None
    radarr_api_key: str = ""

    # ── Plex ─────────────────────────────────────────
    plex_url: Optional[str] = None
    plex_token: str = ""

    # ── TMDB ─────────────────────────────────────────
    tmdb_api_key: str = ""
    tmdb_access_token: str = ""  # Bearer token (Read Access Token)

    # ── LLM ──────────────────────────────────────────
    llm_provider: Literal["openai", "gemini"] = "openai"
    openai_api_key: str = ""
    gemini_api_key: str = ""

    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Chat model used for vibe profiling & query expansion
    openai_chat_model: str = "gpt-4o-mini"
    gemini_chat_model: str = "gemini-1.5-flash"

    # ── Overseerr ────────────────────────────────────
    overseerr_url: Optional[str] = None
    overseerr_api_key: str = ""

    # ── Search tuning ────────────────────────────────
    # Minimum local vector results before triggering TMDB discovery
    discovery_threshold: int = 5
    # pgvector cosine distance cutoff (0 = identical, 2 = opposite)
    vector_distance_cutoff: float = 0.55

    # ── Few-shot feedback ────────────────────────────
    # Number of liked examples to inject into query expansion prompts
    feedback_few_shot_count: int = 5


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]


def reset_settings() -> None:
    """Clear the settings cache so the next call reloads from env + config file."""
    get_settings.cache_clear()
