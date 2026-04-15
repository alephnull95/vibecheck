"""
api/routes/search.py – POST /search

Two-stage hybrid search: LLM expansion → pgvector retrieval → TMDB discovery.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import SearchRequest, SearchResponse
from app.services import search as search_svc

router = APIRouter()


@router.post("/search", response_model=SearchResponse, summary="Vibe Search")
def vibe_search(payload: SearchRequest, db: Session = Depends(get_db)):
    """
    Submit an abstract vibe description.

    - **Stage 1 – Expansion**: The LLM expands the query into rich descriptive prose.
    - **Stage 2 – Retrieval**: pgvector cosine search against indexed movie embeddings.
    - **Discovery fallback**: If local results < threshold, TMDB is queried and
      results are annotated with Overseerr request links.

    Set `save_as` to persist this search and push a Plex collection.
    """
    try:
        result = search_svc.run_search(
            db=db,
            query=payload.query,
            limit=payload.limit,
            save_as=payload.save_as,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SearchResponse(**result)
