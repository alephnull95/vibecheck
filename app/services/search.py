"""
services/search.py – Hybrid search orchestration.

Two-stage pipeline:
  Stage 1 – Expansion : LLM expands the abstract user query into rich prose.
  Stage 2 – Retrieval : pgvector cosine search against indexed movie embeddings.

Discovery fallback:
  If local results < DISCOVERY_THRESHOLD, query TMDB and annotate results with
  Overseerr request URLs, filtering out movies the user already owns.
"""

from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Feedback, Movie, SavedSearch
from app.schemas import DiscoveryMatch, LocalMatch, MovieOut
from app.services import llm as llm_svc
from app.services import overseerr as overseerr_svc
from app.services import plex as plex_svc
from app.services import radarr as radarr_svc
from app.services import tmdb as tmdb_svc

logger = structlog.get_logger(__name__)
settings = get_settings()


def run_search(
    db: Session,
    query: str,
    limit: int = 20,
    save_as: Optional[str] = None,
) -> dict:
    """
    Execute a full vibe search and optionally persist + push to Plex.

    Returns a dict matching the SearchResponse schema.
    """
    # ── 1. Gather few-shot liked examples for personalised expansion ──────────
    liked_profiles = _get_liked_profiles(db)

    # ── 2. Expand the query ───────────────────────────────────────────────────
    expanded = llm_svc.expand_query(query, liked_examples=liked_profiles)
    logger.info("Query expanded", original=query[:80], expanded=expanded[:120])

    # ── 3. Embed the expanded query ───────────────────────────────────────────
    query_embedding = llm_svc.embed_text(expanded)

    # ── 4. pgvector cosine search ─────────────────────────────────────────────
    local_matches = _vector_search(db, query_embedding, limit)

    # ── 5. Discovery fallback ─────────────────────────────────────────────────
    discovery_matches: list[DiscoveryMatch] = []
    if len(local_matches) < settings.discovery_threshold:
        discovery_matches = _discovery_search(db, expanded, limit)

    # ── 6. Optionally persist and push Plex collection ────────────────────────
    saved_search_id: Optional[int] = None
    plex_pushed = False

    if save_as:
        saved_search_id, plex_pushed = _save_and_push(
            db=db,
            name=save_as,
            raw_query=query,
            expanded_query=expanded,
            query_embedding=query_embedding,
            local_matches=local_matches,
        )

    return {
        "query": query,
        "expanded_query": expanded,
        "local_matches": local_matches,
        "discovery_matches": discovery_matches,
        "saved_search_id": saved_search_id,
        "plex_collection_pushed": plex_pushed,
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _vector_search(
    db: Session,
    embedding: list[float],
    limit: int,
) -> list[LocalMatch]:
    """
    Use pgvector's <=> operator (cosine distance) to find the nearest films.
    Distance is converted to similarity score: similarity = 1 - distance.
    """
    # pgvector requires the embedding as a literal string like '[0.1, 0.2, ...]'
    embedding_literal = "[" + ",".join(str(v) for v in embedding) + "]"

    sql = text(
        """
        SELECT
            id,
            1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM movies
        WHERE
            embedding IS NOT NULL
            AND 1 - (embedding <=> CAST(:embedding AS vector)) >= :cutoff
        ORDER BY similarity DESC
        LIMIT :limit
        """
    )
    rows = db.execute(
        sql,
        {
            "embedding": embedding_literal,
            "cutoff": 1.0 - settings.vector_distance_cutoff,
            "limit": limit,
        },
    ).fetchall()

    results: list[LocalMatch] = []
    for row in rows:
        movie = db.get(Movie, row.id)
        if movie:
            results.append(
                LocalMatch(movie=MovieOut.model_validate(movie), similarity=round(row.similarity, 4))
            )

    logger.info("Vector search complete", count=len(results))
    return results


def _discovery_search(
    db: Session,
    expanded_query: str,
    limit: int,
) -> list[DiscoveryMatch]:
    """
    Query TMDB for thematically similar films and filter out movies that are
    already in Radarr (i.e. already owned).
    """
    try:
        owned_tmdb_ids = radarr_svc.get_owned_tmdb_ids()
    except Exception as exc:
        logger.warning("Could not fetch owned TMDb IDs from Radarr", error=str(exc))
        owned_tmdb_ids = set()

    # Use the first ~120 chars of expanded text as the TMDB search term
    search_term = expanded_query[:120]

    try:
        raw_results = tmdb_svc.discover_by_keywords(search_term)
    except Exception as exc:
        logger.warning("TMDB discovery failed", error=str(exc))
        return []

    matches: list[DiscoveryMatch] = []
    for raw in raw_results:
        tmdb_id = raw.get("id")
        if not tmdb_id or tmdb_id in owned_tmdb_ids:
            continue

        normalised = tmdb_svc.normalise_result(raw)
        matches.append(
            DiscoveryMatch(
                **normalised,
                overseerr_request_url=overseerr_svc.request_url_for_tmdb(tmdb_id),
            )
        )
        if len(matches) >= limit:
            break

    logger.info("Discovery results", count=len(matches))
    return matches


def _get_liked_profiles(db: Session) -> list[dict]:
    """
    Fetch vibe profiles for the top-N most-recently liked movies,
    to be used as few-shot examples in query expansion.
    """
    rows = (
        db.query(Movie.vibe_profile)
        .join(Feedback, Feedback.movie_id == Movie.id)
        .filter(Feedback.rating == 1, Movie.vibe_profile.isnot(None))
        .order_by(Feedback.created_at.desc())
        .limit(settings.feedback_few_shot_count)
        .all()
    )
    return [r.vibe_profile for r in rows if r.vibe_profile]


def _save_and_push(
    db: Session,
    name: str,
    raw_query: str,
    expanded_query: str,
    query_embedding: list[float],
    local_matches: list[LocalMatch],
) -> tuple[int, bool]:
    """
    Persist the search and push a Plex collection with the matched films.
    Returns (saved_search_id, plex_pushed_bool).
    """
    saved = SavedSearch(
        name=name,
        raw_query=raw_query,
        expanded_query=expanded_query,
        embedding=query_embedding,
    )
    db.add(saved)
    db.flush()

    plex_pushed = False
    plex_rating_keys = [
        m.movie.plex_rating_key
        for m in local_matches
        if m.movie.plex_rating_key is not None
    ]

    if plex_rating_keys:
        try:
            result = plex_svc.push_collection(
                collection_title=name,
                plex_rating_keys=plex_rating_keys,
            )
            saved.plex_collection_id = result["collection_key"]
            plex_pushed = True
        except Exception as exc:
            logger.warning("Plex collection push failed", error=str(exc))

    db.commit()
    return saved.id, plex_pushed
