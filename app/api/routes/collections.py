"""
api/routes/collections.py – Plex Smart Collection management.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SavedSearch
from app.schemas import CollectionPushRequest, CollectionPushResult
from app.services import plex as plex_svc

router = APIRouter()


@router.post(
    "/collections/push",
    response_model=CollectionPushResult,
    summary="Push Saved Search → Plex Collection",
)
def push_collection(payload: CollectionPushRequest, db: Session = Depends(get_db)):
    """
    Re-run the vector search for a saved search and push the results as a
    Plex collection. Overwrites any existing collection with the same name.

    This is useful for refreshing a collection after new movies are indexed.
    """
    saved = db.get(SavedSearch, payload.saved_search_id)
    if not saved:
        raise HTTPException(status_code=404, detail="Saved search not found.")

    if saved.embedding is None:
        raise HTTPException(
            status_code=422,
            detail="This saved search has no embedding. Re-run the search first.",
        )

    # Re-run vector search using the saved embedding
    from app.services.search import _vector_search  # noqa: PLC0415
    matches = _vector_search(db, saved.embedding, limit=50)

    plex_rating_keys = [
        m.movie.plex_rating_key
        for m in matches
        if m.movie.plex_rating_key is not None
    ]

    if not plex_rating_keys:
        raise HTTPException(
            status_code=422,
            detail="No Plex-available movies found for this search.",
        )

    try:
        result = plex_svc.push_collection(
            collection_title=saved.name,
            plex_rating_keys=plex_rating_keys,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    saved.plex_collection_id = result["collection_key"]
    db.commit()

    return CollectionPushResult(**result)


@router.get("/collections", summary="List Saved Searches / Collections")
def list_collections(db: Session = Depends(get_db)):
    """Return all saved searches (which are the basis for Plex collections)."""
    rows = db.query(SavedSearch).order_by(SavedSearch.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "raw_query": r.raw_query,
            "plex_collection_id": r.plex_collection_id,
            "created_at": r.created_at,
        }
        for r in rows
    ]
