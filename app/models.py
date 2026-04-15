"""
models.py – SQLAlchemy ORM models mirroring the SQL schema in 001_initial.sql.
"""

from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

EMBEDDING_DIM = 1536  # OpenAI text-embedding-3-small


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # External IDs
    radarr_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    plex_rating_key: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True)
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True)

    # Metadata
    title: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    genres: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text), nullable=True)
    runtime_minutes: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    poster_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # AI vibe profile
    vibe_profile: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # pgvector embedding
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    feedback: Mapped[list["Feedback"]] = relationship("Feedback", back_populates="movie", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Movie id={self.id} radarr_id={self.radarr_id} title={self.title!r}>"


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    raw_query: Mapped[str] = mapped_column(Text, nullable=False)
    expanded_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    plex_collection_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    feedback: Mapped[list["Feedback"]] = relationship("Feedback", back_populates="search")

    def __repr__(self) -> str:
        return f"<SavedSearch id={self.id} name={self.name!r}>"


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("movie_id", "search_id", name="uq_feedback_movie_search"),
        CheckConstraint("rating IN (1, -1)", name="ck_feedback_rating"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    search_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("saved_searches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1=liked, -1=disliked

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    movie: Mapped["Movie"] = relationship("Movie", back_populates="feedback")
    search: Mapped[Optional["SavedSearch"]] = relationship("SavedSearch", back_populates="feedback")

    def __repr__(self) -> str:
        return f"<Feedback id={self.id} movie_id={self.movie_id} rating={self.rating}>"
