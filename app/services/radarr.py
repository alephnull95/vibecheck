"""
services/radarr.py – Radarr v3 API client.

Used by the sync worker to pull the full movie library and cross-reference
what VibeCheck already has indexed.
"""

from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_BASE = str(settings.radarr_url).rstrip("/")
_HEADERS = {"X-Api-Key": settings.radarr_api_key}
_TIMEOUT = 30.0


def _client() -> httpx.Client:
    return httpx.Client(base_url=_BASE, headers=_HEADERS, timeout=_TIMEOUT)


def get_all_movies() -> list[dict[str, Any]]:
    """
    Return the full Radarr movie list.
    Each item contains at minimum: id, title, year, overview, genres,
    tmdbId, runtime, hasFile.
    """
    with _client() as c:
        response = c.get("/api/v3/movie")
        response.raise_for_status()
        movies = response.json()
    logger.info("Fetched movies from Radarr", count=len(movies))
    return movies


def get_movie(radarr_id: int) -> Optional[dict[str, Any]]:
    """Fetch a single movie record by Radarr ID."""
    with _client() as c:
        response = c.get(f"/api/v3/movie/{radarr_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


def get_owned_tmdb_ids() -> set[int]:
    """Return a set of TMDB IDs for all movies currently in Radarr."""
    movies = get_all_movies()
    return {m["tmdbId"] for m in movies if m.get("tmdbId")}
