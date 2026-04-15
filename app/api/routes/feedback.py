"""
api/routes/feedback.py – Thumbs-up / thumbs-down on search results.

Stored preferences are used as few-shot examples in the Query Expander
(see services/llm.py :: expand_query) to calibrate results to personal taste.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.database import get_db
from app.models import Feedback, Movie, SavedSearch
from app.schemas import FeedbackOut, FeedbackRequest

router = APIRouter()


@router.post("/feedback", response_model=FeedbackOut, status_code=201, summary="Submit Feedback")
def submit_feedback(payload: FeedbackRequest, db: Session = Depends(get_db)):
    """
    Record a thumbs-up (rating=1) or thumbs-down (rating=-1) for a movie,
    optionally scoped to a saved search.

    Subsequent vibe searches will incorporate liked films into the LLM Query
    Expander via few-shot prompting.
    """
    # Validate references
    movie = db.get(Movie, payload.movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found.")

    if payload.search_id is not None:
        search = db.get(SavedSearch, payload.search_id)
        if not search:
            raise HTTPException(status_code=404, detail="Saved search not found.")

    # Upsert: update rating if a record already exists for this movie+search
    existing = (
        db.query(Feedback)
        .filter_by(movie_id=payload.movie_id, search_id=payload.search_id)
        .first()
    )
    if existing:
        existing.rating = payload.rating
        db.commit()
        db.refresh(existing)
        return FeedbackOut.model_validate(existing)

    feedback = Feedback(
        movie_id=payload.movie_id,
        search_id=payload.search_id,
        rating=payload.rating,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return FeedbackOut.model_validate(feedback)


@router.get("/feedback", summary="List All Feedback")
def list_feedback(
    movie_id: int | None = None,
    search_id: int | None = None,
    db: Session = Depends(get_db),
):
    """List feedback records enriched with movie title and year."""
    q = (
        db.query(Feedback, Movie.title, Movie.year)
        .join(Movie, Movie.id == Feedback.movie_id)
    )
    if movie_id is not None:
        q = q.filter(Feedback.movie_id == movie_id)
    if search_id is not None:
        q = q.filter(Feedback.search_id == search_id)
    rows = q.order_by(Feedback.created_at.desc()).limit(200).all()
    results = []
    for fb, title, year in rows:
        out = FeedbackOut.model_validate(fb)
        out.movie_title = title
        out.movie_year = year
        results.append(out)
    return results


@router.delete("/feedback/{feedback_id}", status_code=204, summary="Delete Feedback")
def delete_feedback(feedback_id: int, db: Session = Depends(get_db)):
    """Remove a feedback record."""
    fb = db.get(Feedback, feedback_id)
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found.")
    db.delete(fb)
    db.commit()
