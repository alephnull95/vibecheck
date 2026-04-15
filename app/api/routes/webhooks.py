"""
api/routes/webhooks.py – Plex webhook receiver.

Configure Plex to send webhooks to:
  http://<mac-mini-ip>:8000/api/v1/webhooks/plex

In Plex:  Settings → Webhooks → Add Webhook

Events handled:
  library.new  – a new movie was added to the Plex library.
                 We update the plex_rating_key on the DB record and trigger
                 profiling if the movie isn't indexed yet.
All other events are acknowledged and ignored.
"""

import json
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException

from app.database import SessionLocal
from app.models import Movie

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/webhooks/plex", summary="Plex Webhook Receiver")
async def plex_webhook(
    background_tasks: BackgroundTasks,
    payload: Annotated[str, Form()],
):
    """
    Receives multipart/form-data from Plex.
    The `payload` field contains the JSON event object.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    event = data.get("event", "")
    metadata = data.get("Metadata", {})

    logger.info("Plex webhook received", event=event, media_type=metadata.get("type"))

    # Only care about new movies
    if event != "library.new" or metadata.get("type") != "movie":
        return {"status": "ignored", "event": event}

    rating_key_raw = metadata.get("ratingKey")
    rating_key = int(rating_key_raw) if rating_key_raw else None

    # Extract TMDB ID from the Guid list
    tmdb_id: int | None = None
    for guid in metadata.get("Guid", []):
        gid = guid.get("id", "")
        if gid.startswith("tmdb://"):
            try:
                tmdb_id = int(gid.removeprefix("tmdb://"))
            except ValueError:
                pass
            break

    background_tasks.add_task(_handle_new_movie, rating_key=rating_key, tmdb_id=tmdb_id)
    return {"status": "accepted", "rating_key": rating_key, "tmdb_id": tmdb_id}


def _handle_new_movie(rating_key: int | None, tmdb_id: int | None) -> None:
    """
    Background task: find or create the movie record, update the
    plex_rating_key, and trigger profiling if the movie isn't indexed yet.
    """
    from app.workers.tasks import profile_movie, run_radarr_sync  # noqa: PLC0415

    db = SessionLocal()
    try:
        movie: Movie | None = None

        if tmdb_id:
            movie = db.query(Movie).filter_by(tmdb_id=tmdb_id).first()
        if movie is None and rating_key:
            movie = db.query(Movie).filter_by(plex_rating_key=rating_key).first()

        if movie:
            # Stamp the Plex rating key if we didn't have it
            if rating_key and movie.plex_rating_key != rating_key:
                movie.plex_rating_key = rating_key
                db.commit()
                logger.info("Updated plex_rating_key", movie_id=movie.id, rating_key=rating_key)

            # Trigger profiling if still unindexed
            if movie.indexed_at is None:
                profile_movie.apply_async(args=[movie.id])
                logger.info("Triggered profile_movie via Plex webhook", movie_id=movie.id)
        else:
            # Movie not in DB yet — trigger a full Radarr sync to pick it up
            logger.info("Unknown movie from Plex webhook; triggering Radarr sync", tmdb_id=tmdb_id, rating_key=rating_key)
            run_radarr_sync.apply_async()
    finally:
        db.close()
