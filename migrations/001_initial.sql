-- VibeCheck – initial schema
-- Run automatically by Docker when the container is first created.

CREATE EXTENSION IF NOT EXISTS vector;

-- ──────────────────────────────────────────────────────────────────────────────
-- movies
-- Central record per film. Populated by the Radarr sync worker.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS movies (
    id              SERIAL PRIMARY KEY,

    -- External IDs
    radarr_id       INTEGER  UNIQUE NOT NULL,
    plex_rating_key INTEGER  UNIQUE,          -- null until Plex confirms availability
    tmdb_id         INTEGER  UNIQUE,

    -- Basic metadata (cached locally to avoid repeated API calls)
    title           TEXT     NOT NULL,
    year            SMALLINT,
    overview        TEXT,
    genres          TEXT[],                    -- e.g. ARRAY['Thriller','Sci-Fi']
    runtime_minutes SMALLINT,
    poster_path     TEXT,                      -- relative TMDB path

    -- AI-generated vibe profile (structured JSON from LLM)
    -- Schema: { "atmosphere": "...", "themes": "...", "mood": "...", "keywords": [...] }
    vibe_profile    JSONB,

    -- pgvector embedding (1536 dims – OpenAI text-embedding-3-small)
    embedding       vector(1536),

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    indexed_at      TIMESTAMPTZ           -- set when embedding is written; NULL = not yet indexed
);

-- Index for fast approximate neighbour search (cosine distance)
CREATE INDEX IF NOT EXISTS movies_embedding_cosine_idx
    ON movies USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ──────────────────────────────────────────────────────────────────────────────
-- saved_searches
-- Persisted "vibe searches" that drive Plex Smart Collections.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS saved_searches (
    id              SERIAL PRIMARY KEY,
    name            TEXT     NOT NULL UNIQUE,  -- e.g. "The Grime"
    raw_query       TEXT     NOT NULL,         -- original user input
    expanded_query  TEXT,                      -- LLM-expanded terms (stored for re-use)
    -- The centroid embedding of this search (recomputed on save)
    embedding       vector(1536),
    plex_collection_id  TEXT,                  -- Plex ratingKey if collection was pushed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────────────────────────────────────
-- feedback
-- Thumbs-up / thumbs-down on individual search results.
-- Used for few-shot prompting in the Query Expander.
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feedback (
    id              SERIAL PRIMARY KEY,
    movie_id        INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    search_id       INTEGER REFERENCES saved_searches(id) ON DELETE SET NULL,
    rating          SMALLINT NOT NULL CHECK (rating IN (1, -1)),  -- 1=liked, -1=disliked
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (movie_id, search_id)   -- one vote per movie per search
);

-- ──────────────────────────────────────────────────────────────────────────────
-- Trigger: keep updated_at current
-- ──────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER movies_updated_at
    BEFORE UPDATE ON movies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER saved_searches_updated_at
    BEFORE UPDATE ON saved_searches
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
