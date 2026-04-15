"""
services/plex.py – Plex Smart Collection manager via python-plexapi.

Creates or updates Plex collections that are backed by a saved vibe search.
Collections are rebuilt by passing the matched movie's plex_rating_key values
directly, giving us fine-grained control without relying on Plex Smart Filters
(which are limited to indexed metadata fields).
"""

from typing import Optional

import structlog
from plexapi.exceptions import NotFound
from plexapi.server import PlexServer

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


def _server() -> PlexServer:
    return PlexServer(str(settings.plex_url), settings.plex_token)


def _movie_section(plex: PlexServer):
    """Return the first Movies library section."""
    for section in plex.library.sections():
        if section.type == "movie":
            return section
    raise RuntimeError("No movie library section found in Plex.")


def push_collection(
    collection_title: str,
    plex_rating_keys: list[int],
) -> dict:
    """
    Create or fully replace a Plex collection named *collection_title*
    containing the movies identified by *plex_rating_keys*.

    Returns a dict with collection_key, collection_title, movie_count.
    """
    plex = _server()
    section = _movie_section(plex)

    # Fetch movie objects that Plex actually knows about
    items = []
    for key in plex_rating_keys:
        try:
            item = plex.fetchItem(key)
            items.append(item)
        except NotFound:
            logger.warning("Plex item not found, skipping", rating_key=key)

    # Remove existing collection with the same name if it exists
    try:
        existing = section.collection(collection_title)
        existing.delete()
        logger.info("Deleted existing Plex collection", title=collection_title)
    except NotFound:
        pass

    if not items:
        logger.warning("No valid Plex items; skipping collection creation", title=collection_title)
        return {"collection_key": "", "collection_title": collection_title, "movie_count": 0}

    collection = section.createCollection(title=collection_title, items=items)
    logger.info(
        "Plex collection pushed",
        title=collection_title,
        key=collection.ratingKey,
        count=len(items),
    )
    return {
        "collection_key": str(collection.ratingKey),
        "collection_title": collection.title,
        "movie_count": len(items),
    }


def get_plex_rating_key(tmdb_id: int) -> Optional[int]:
    """
    Look up a Plex rating key by matching the movie's TMDB ID via the
    Plex metadata agent. Returns None if the movie isn't in Plex.
    """
    plex = _server()
    section = _movie_section(plex)
    try:
        results = section.search(filters={"guid": f"tmdb://{tmdb_id}"})
        if results:
            return results[0].ratingKey
    except Exception as exc:  # noqa: BLE001
        logger.warning("Plex rating key lookup failed", tmdb_id=tmdb_id, error=str(exc))
    return None
