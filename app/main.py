"""
main.py – FastAPI application factory and root router mount.
"""

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.api.routes import collections, feedback, search, setup, sync, webhooks

logger = structlog.get_logger(__name__)
settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(
        title="VibeCheck",
        description="Semantic discovery engine and Plex curator for a 10 000+ movie library.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS – tighten in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_env == "development" else [],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(search.router, prefix="/api/v1", tags=["Search"])
    app.include_router(sync.router, prefix="/api/v1", tags=["Sync"])
    app.include_router(collections.router, prefix="/api/v1", tags=["Collections"])
    app.include_router(feedback.router, prefix="/api/v1", tags=["Feedback"])
    app.include_router(webhooks.router, prefix="/api/v1", tags=["Webhooks"])
    app.include_router(setup.router, prefix="/api/v1", tags=["Setup"])

    # ── Health ────────────────────────────────────────────────────────────────
    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok"}

    # ── Redirect root → UI ────────────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/ui/index.html")

    # ── Static frontend (served last so API routes take priority) ─────────────
    app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")

    logger.info("VibeCheck API started", env=settings.app_env)
    return app


app = create_app()
