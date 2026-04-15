# VibeCheck

Semantic discovery engine and Plex curator for 10 000+ movie libraries.  
Maps abstract "vibes" to specific films using LLM query expansion + pgvector similarity search.

---

## Quick Start

```bash
# 1. Copy and fill in your API keys
cp .env.example .env
nano .env

# 2. Start the stack
docker compose up -d

# 3. Trigger the initial Radarr sync (indexes all movies + generates AI profiles)
curl -X POST http://localhost:8000/api/v1/sync/radarr

# 4. Poll the task until status=success
curl http://localhost:8000/api/v1/sync/status/<task_id>

# 5. Run a vibe search
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "gritty industrial apocalypse with moral ambiguity", "limit": 10}'

# 6. Save a search + push it as a Plex collection
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "The Grime", "limit": 20, "save_as": "The Grime"}'
```

API docs: http://localhost:8000/docs  
Celery dashboard: http://localhost:5555

---

## Architecture

```
┌──────────────┐    POST /search     ┌─────────────────────────────────────┐
│   Client UI  │ ─────────────────►  │  FastAPI  (api container, :8000)    │
└──────────────┘                     └──────────┬──────────────────────────┘
                                                │
                    ┌───────────────────────────┴──────────────────────────┐
                    │                                                      │
            ┌───────▼────────┐                                   ┌────────▼───────┐
            │  LLM Service   │  expand_query()                   │ Vector Search  │
            │  (OpenAI /     │  embed_text()     pgvector <=>    │  PostgreSQL +  │
            │   Gemini)      │                   cosine search   │  pgvector      │
            └───────┬────────┘                                   └────────┬───────┘
                    │                                                      │
            ┌───────▼──────────────────────────────────────────────────────▼─────┐
            │  Discovery fallback: TMDB → filter owned (Radarr) → Overseerr URL  │
            └─────────────────────────────────────────────────────────────────────┘

POST /sync/radarr  →  Celery Worker  →  Radarr sync  →  fan-out profile_movie tasks
                                                          (LLM vibe profile + embed)
```

## Module Map

| File | Responsibility |
|---|---|
| `app/config.py` | Pydantic-settings: all env vars, validation |
| `app/models.py` | SQLAlchemy ORM: `movies`, `saved_searches`, `feedback` |
| `app/services/llm.py` | LLM vibe profiling, query expansion, embeddings |
| `app/services/search.py` | Hybrid search orchestration |
| `app/services/radarr.py` | Radarr v3 API client |
| `app/services/tmdb.py` | TMDB discovery client |
| `app/services/plex.py` | Plex collection manager (python-plexapi) |
| `app/services/overseerr.py` | Overseerr request URL generator |
| `app/workers/tasks.py` | Celery tasks: `run_radarr_sync`, `profile_movie` |
| `app/api/routes/search.py` | `POST /search` |
| `app/api/routes/sync.py` | `POST /sync/radarr`, `GET /sync/status/{id}` |
| `app/api/routes/collections.py` | Plex collection push/list |
| `app/api/routes/feedback.py` | Thumbs-up/down (trains few-shot expander) |
| `migrations/001_initial.sql` | PostgreSQL schema + pgvector index |

## Key Design Decisions

- **Idempotent sync**: `run_radarr_sync` only enqueues `profile_movie` for movies where `indexed_at IS NULL`. Re-running is safe.
- **Few-shot personalisation**: `expand_query()` injects the top-N liked vibe profiles into the LLM system prompt so the semantic expansion drifts toward your taste over time.
- **Discovery threshold**: If vector search returns fewer than `DISCOVERY_THRESHOLD` (default 5) local results, TMDB is queried automatically. Owned titles (matching Radarr's TMDB IDs) are filtered out.
- **Plex collections**: Saved searches store a centroid embedding. The `/collections/push` endpoint re-runs the vector search and rebuilds the Plex collection — run it after a new batch of movies is indexed.
