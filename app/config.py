"""
config.py – Central settings for VibeCheck.

All values are loaded from environment variables (or a .env file).
Copy .env.example to .env and fill in your keys before starting.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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
    radarr_url: AnyHttpUrl
    radarr_api_key: str

    # ── Plex ─────────────────────────────────────────
    plex_url: AnyHttpUrl
    plex_token: str

    # ── TMDB ─────────────────────────────────────────
    tmdb_api_key: str
    tmdb_access_token: str  # Bearer token (Read Access Token)

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
    overseerr_url: AnyHttpUrl
    overseerr_api_key: str

    # ── Search tuning ────────────────────────────────
    # Minimum local vector results before triggering TMDB discovery
    discovery_threshold: int = 5
    # pgvector cosine similarity cutoff (0 = identical, 2 = opposite)
    vector_distance_cutoff: float = 0.55

    # ── Few-shot feedback ────────────────────────────
    # Number of liked examples to inject into query expansion prompts
    feedback_few_shot_count: int = 5

    @model_validator(mode="after")
    def _validate_llm_keys(self) -> "Settings":
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]
