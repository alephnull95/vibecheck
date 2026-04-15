"""
workers/tasks.py – Celery tasks for ingestion and AI profiling.

Task: run_radarr_sync
─────────────────────
  1. Pulls all movies from Radarr.
  2. Upserts basic metadata into the `movies` table (idempotent).
  3. Enqueues a `profile_movie` sub-task for every movie that does NOT yet
     have an embedding (indexed_at IS NULL).

Task: profile_movie
────────────────────
  1. Fetches the movie record from DB.
  2. Calls the LLM to generate a structured Vibe Profile.
  3. Converts the profile text into a 1536-dim embedding.
  4. Writes the vibe_profile + embedding + indexed_at back to DB.
  (Idempotent: skips movies that already have an embedding unless forced.)
"""

import structlog
from celery import group
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models import Movie
from app.services import radarr as radarr_svc
from app.services import llm as llm_svc

logger = structlog.get_logger(__name__)


# ── Radarr sync ───────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.workers.tasks.run_radarr_sync", max_retries=2)
def run_radarr_sync(self) -> dict:
    """
    Pull Radarr library, upsert movies, and enqueue profiling for un-indexed
    movies. Returns a summary dict.
    """
    logger.info("Radarr sync started")
    try:
        radarr_movies = radarr_svc.get_all_movies()
    except Exception as exc:
        logger.error("Failed to fetch Radarr library", error=str(exc))
        raise self.retry(exc=exc, countdown=60)

    db = SessionLocal()
    try:
        upserted = 0
        to_profile: list[int] = []

        for rm in radarr_movies:
            radarr_id = rm["id"]
            existing = db.query(Movie).filter_by(radarr_id=radarr_id).first()

            genres = [g["name"] for g in rm.get("genres", []) if "name" in g]
            poster = None
            for img in rm.get("images", []):
                if img.get("coverType") == "poster":
                    poster = img.get("remoteUrl") or img.get("url")
                    break

            if existing is None:
                movie = Movie(
                    radarr_id=radarr_id,
                    tmdb_id=rm.get("tmdbId"),
                    title=rm.get("title", "Unknown"),
                    year=rm.get("year"),
                    overview=rm.get("overview"),
                    genres=genres or None,
                    runtime_minutes=rm.get("runtime"),
                    poster_path=poster,
                )
                db.add(movie)
                db.flush()
                to_profile.append(movie.id)
                upserted += 1
            else:
                # Update mutable metadata fields but do NOT overwrite embeddings
                existing.title = rm.get("title", existing.title)
                existing.year = rm.get("year", existing.year)
                existing.overview = rm.get("overview", existing.overview)
                existing.genres = genres or existing.genres
                existing.runtime_minutes = rm.get("runtime", existing.runtime_minutes)
                existing.poster_path = poster or existing.poster_path
                if existing.tmdb_id is None and rm.get("tmdbId"):
                    existing.tmdb_id = rm["tmdbId"]
                if existing.indexed_at is None:
                    to_profile.append(existing.id)
                upserted += 1

        db.commit()
    finally:
        db.close()

    # Fan out profile tasks for un-indexed movies
    if to_profile:
        job = group(profile_movie.s(movie_id) for movie_id in to_profile)
        job.apply_async()
        logger.info("Enqueued profiling tasks", count=len(to_profile))

    summary = {
        "radarr_total": len(radarr_movies),
        "upserted": upserted,
        "profiling_queued": len(to_profile),
    }
    logger.info("Radarr sync complete", **summary)
    return summary


# ── AI Profiling ──────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.workers.tasks.profile_movie", max_retries=3)
def profile_movie(self, movie_id: int, force: bool = False) -> dict:
    """
    Generate a Vibe Profile + embedding for a single movie and persist it.
    Idempotent: skips if indexed_at is already set, unless *force=True*.
    """
    db = SessionLocal()
    try:
        movie = db.query(Movie).filter_by(id=movie_id).first()
        if movie is None:
            logger.warning("profile_movie: movie not found", movie_id=movie_id)
            return {"skipped": True, "reason": "not_found"}

        if movie.indexed_at is not None and not force:
            logger.debug("profile_movie: already indexed, skipping", movie_id=movie_id)
            return {"skipped": True, "reason": "already_indexed"}

        # ── Step 1: Generate vibe profile from LLM
        try:
            vibe_profile = llm_svc.generate_vibe_profile(
                title=movie.title,
                year=movie.year,
                overview=movie.overview,
                genres=movie.genres,
            )
        except Exception as exc:
            logger.error("LLM vibe profile failed", movie_id=movie_id, error=str(exc))
            raise self.retry(exc=exc, countdown=30)

        # ── Step 2: Embed the profile
        # Concatenate narrative fields into a single string for embedding
        embed_text = _profile_to_text(vibe_profile, movie.title, movie.year)
        try:
            embedding = llm_svc.embed_text(embed_text)
        except Exception as exc:
            logger.error("Embedding failed", movie_id=movie_id, error=str(exc))
            raise self.retry(exc=exc, countdown=30)

        # ── Step 3: Persist
        movie.vibe_profile = vibe_profile
        movie.embedding = embedding
        movie.indexed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("Movie profiled", movie_id=movie_id, title=movie.title)
        return {"movie_id": movie_id, "title": movie.title, "indexed": True}

    finally:
        db.close()


def _profile_to_text(profile: dict, title: str, year: int | None) -> str:
    """
    Concatenate vibe profile fields into a single string for embedding.
    Prepend the title so the vector encodes the film's identity too.
    """
    parts = [
        f"Title: {title} ({year or 'unknown year'})",
        profile.get("atmosphere", ""),
        profile.get("themes", ""),
        profile.get("mood", ""),
        " ".join(profile.get("keywords", [])),
    ]
    return " ".join(p for p in parts if p)


# ── Plex collection refresh ───────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.workers.tasks.refresh_all_plex_collections", max_retries=2)
def refresh_all_plex_collections(self) -> dict:
    """
    Rebuild every saved Plex collection using the current vector index.
    Run nightly after the Radarr sync so newly-indexed films appear in
    existing collections automatically.
    """
    from app.models import SavedSearch  # noqa: PLC0415
    from app.services import plex as plex_svc  # noqa: PLC0415
    from app.services.search import _vector_search  # noqa: PLC0415

    db = SessionLocal()
    try:
        searches = (
            db.query(SavedSearch)
            .filter(
                SavedSearch.plex_collection_id.isnot(None),
                SavedSearch.embedding.isnot(None),
            )
            .all()
        )

        refreshed, failed = 0, 0
        for ss in searches:
            matches = _vector_search(db, ss.embedding, limit=50)
            plex_keys = [m.movie.plex_rating_key for m in matches if m.movie.plex_rating_key]
            if not plex_keys:
                continue
            try:
                result = plex_svc.push_collection(
                    collection_title=ss.name,
                    plex_rating_keys=plex_keys,
                )
                ss.plex_collection_id = result["collection_key"]
                refreshed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Collection refresh failed", name=ss.name, error=str(exc))
                failed += 1

        db.commit()
        summary = {"refreshed": refreshed, "failed": failed, "total": len(searches)}
        logger.info("Plex collections refreshed", **summary)
        return summary
    finally:
        db.close()
