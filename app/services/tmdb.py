"""
services/tmdb.py – TMDB API v3 client.

Used for the Discovery Track: when local vector search yields fewer than
DISCOVERY_THRESHOLD results, we query TMDB for thematically similar films,
then filter out anything the user already owns (via Radarr).
"""

from typing import Any

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
_BASE = "https://api.themoviedb.org/3"
_POSTER_BASE = "https://image.tmdb.org/t/p/w500"
_TIMEOUT = 15.0


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        base_url=_BASE,
        headers={
            "Authorization": f"Bearer {s.tmdb_access_token}",
            "accept": "application/json",
        },
        timeout=_TIMEOUT,
    )


def search_movies(query: str, page: int = 1) -> list[dict[str, Any]]:
    """Full-text search against TMDB movie catalogue."""
    with _client() as c:
        r = c.get("/search/movie", params={"query": query, "page": page, "include_adult": False})
        r.raise_for_status()
        results = r.json().get("results", [])
    logger.debug("TMDB search", query=query[:80], count=len(results))
    return results


def discover_by_keywords(keywords: str, page: int = 1) -> list[dict[str, Any]]:
    """
    Use TMDB /discover/movie with a free-text keyword search.
    Runs a keyword lookup first to get keyword IDs, then discovers movies.
    Falls back to a plain /search/movie call if no keyword IDs are found.
    """
    keyword_ids = _resolve_keyword_ids(keywords)
    if not keyword_ids:
        return search_movies(keywords, page)

    with _client() as c:
        r = c.get(
            "/discover/movie",
            params={
                "with_keywords": "|".join(str(k) for k in keyword_ids[:5]),
                "sort_by": "popularity.desc",
                "page": page,
                "include_adult": False,
            },
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    logger.debug("TMDB discover", keyword_ids=keyword_ids[:5], count=len(results))
    return results


def _resolve_keyword_ids(text: str) -> list[int]:
    """Search TMDB keywords by text and return matching IDs."""
    # Extract first few words as search terms
    terms = text.split()[:6]
    ids: list[int] = []
    with _client() as c:
        for term in terms:
            r = c.get("/search/keyword", params={"query": term})
            if r.is_success:
                for kw in r.json().get("results", [])[:2]:
                    if kw.get("id"):
                        ids.append(kw["id"])
    return list(dict.fromkeys(ids))  # deduplicate, preserve order


def normalise_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw TMDB result dict into a clean, consistent shape."""
    poster = raw.get("poster_path")
    return {
        "tmdb_id": raw.get("id"),
        "title": raw.get("title", ""),
        "year": _extract_year(raw.get("release_date", "")),
        "overview": raw.get("overview", ""),
        "genres": [],  # genre names not returned by search/discover endpoints
        "poster_path": f"{_POSTER_BASE}{poster}" if poster else None,
    }


def _extract_year(release_date: str) -> int | None:
    try:
        return int(release_date[:4]) if release_date else None
    except (ValueError, TypeError):
        return None
