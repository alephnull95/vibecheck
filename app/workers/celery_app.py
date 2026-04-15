"""
workers/celery_app.py – Celery application factory.
"""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "vibecheck",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Route heavy ingestion work to a dedicated queue
    task_routes={
        "app.workers.tasks.profile_movie": {"queue": "ingestion"},
        "app.workers.tasks.run_radarr_sync": {"queue": "ingestion"},
        "app.workers.tasks.refresh_all_plex_collections": {"queue": "default"},
    },
    # ── Scheduled tasks (Celery Beat) ────────────────────────────────────────
    beat_schedule={
        # Pull new Radarr additions nightly at 3 AM UTC
        "radarr-nightly-sync": {
            "task": "app.workers.tasks.run_radarr_sync",
            "schedule": crontab(hour=3, minute=0),
        },
        # Rebuild Plex collections at 4 AM UTC (after sync is likely done)
        "plex-collections-nightly-refresh": {
            "task": "app.workers.tasks.refresh_all_plex_collections",
            "schedule": crontab(hour=4, minute=0),
        },
    },
)
