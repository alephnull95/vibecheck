"""
schemas.py – Pydantic request/response models for all API routes.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Movie ──────────────────────────────────────────────────────────────────────

class MovieBase(BaseModel):
    radarr_id: int
    tmdb_id: Optional[int] = None
    plex_rating_key: Optional[int] = None
    title: str
    year: Optional[int] = None
    overview: Optional[str] = None
    genres: Optional[list[str]] = None
    runtime_minutes: Optional[int] = None
    poster_path: Optional[str] = None


class MovieOut(MovieBase):
    id: int
    vibe_profile: Optional[dict[str, Any]] = None
    indexed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Search ────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500, description="Abstract vibe description, e.g. 'gritty industrial apocalypse'")
    limit: int = Field(default=20, ge=1, le=100)
    save_as: Optional[str] = Field(
        default=None,
        description="If provided, persist this vibe search under this name and push a Plex collection."
    )


class LocalMatch(BaseModel):
    movie: MovieOut
    similarity: float = Field(..., description="Cosine similarity score (0–1, higher = closer match)")


class DiscoveryMatch(BaseModel):
    tmdb_id: int
    title: str
    year: Optional[int] = None
    overview: Optional[str] = None
    genres: Optional[list[str]] = None
    poster_path: Optional[str] = None
    overseerr_request_url: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    expanded_query: str
    local_matches: list[LocalMatch]
    discovery_matches: list[DiscoveryMatch]
    saved_search_id: Optional[int] = Field(default=None, description="ID of the persisted SavedSearch, if save_as was set.")
    plex_collection_pushed: bool = False


# ── Saved Searches ────────────────────────────────────────────────────────────

class SavedSearchOut(BaseModel):
    id: int
    name: str
    raw_query: str
    expanded_query: Optional[str] = None
    plex_collection_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Feedback ──────────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    movie_id: int
    search_id: Optional[int] = None
    rating: int = Field(..., description="1 = liked, -1 = disliked")

    def model_post_init(self, __context: Any) -> None:
        if self.rating not in (1, -1):
            raise ValueError("rating must be 1 (liked) or -1 (disliked)")


class FeedbackOut(BaseModel):
    id: int
    movie_id: int
    search_id: Optional[int] = None
    rating: int
    created_at: datetime
    # Enriched by the list endpoint (not stored in DB)
    movie_title: Optional[str] = None
    movie_year: Optional[int] = None

    model_config = {"from_attributes": True}


# ── Sync ──────────────────────────────────────────────────────────────────────

class SyncStatus(BaseModel):
    task_id: str
    status: str
    message: str


# ── Plex Collections ──────────────────────────────────────────────────────────

class CollectionPushRequest(BaseModel):
    saved_search_id: int


class CollectionPushResult(BaseModel):
    collection_key: str
    collection_title: str
    movie_count: int
