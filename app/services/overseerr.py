"""
services/overseerr.py – Overseerr API client.

Used to generate "Request" links for Discovery Track results so the user
can add unowned films to their library with a single click.
"""

from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_BASE = str(settings.overseerr_url).rstrip("/")
_HEADERS = {
    "X-Api-Key": settings.overseerr_api_key,
    "Content-Type": "application/json",
}
_TIMEOUT = 15.0


def request_url_for_tmdb(tmdb_id: int) -> str:
    """
    Return a deep-link URL to request a movie in the Overseerr UI.
    This is surfaced as a button in Discovery results — the user navigates
    there themselves; we do not programmatically request on their behalf.
    """
    base = str(settings.overseerr_url).rstrip("/")
    return f"{base}/movie/{tmdb_id}"


def get_request_status(tmdb_id: int) -> Optional[dict[str, Any]]:
    """
    Check whether a movie is already requested or available in Overseerr.
    Returns the first matching media record, or None if not found.
    """
    with httpx.Client(base_url=_BASE, headers=_HEADERS, timeout=_TIMEOUT) as c:
        r = c.get(f"/api/v1/movie/{tmdb_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
    return data.get("mediaInfo")
