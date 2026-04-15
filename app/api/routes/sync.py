"""
api/routes/sync.py – Radarr library sync trigger and status endpoints.
"""

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException

from app.schemas import SyncStatus
from app.workers.celery_app import celery_app
from app.workers.tasks import run_radarr_sync

router = APIRouter()


@router.post("/sync/radarr", response_model=SyncStatus, summary="Trigger Radarr Sync")
def trigger_radarr_sync():
    """
    Enqueue a full Radarr library sync.

    The worker will:
    1. Pull all movies from Radarr.
    2. Upsert metadata into the local DB.
    3. Fan out `profile_movie` tasks for every un-indexed film.

    Returns a task ID you can poll with `GET /sync/status/{task_id}`.
    """
    task = run_radarr_sync.apply_async()
    return SyncStatus(task_id=task.id, status="queued", message="Radarr sync enqueued.")


@router.get("/sync/status/{task_id}", response_model=SyncStatus, summary="Get Task Status")
def get_sync_status(task_id: str):
    """Poll the status of a previously enqueued Celery task."""
    result: AsyncResult = celery_app.AsyncResult(task_id)

    if result.state == "PENDING":
        return SyncStatus(task_id=task_id, status="pending", message="Task is waiting to be processed.")
    if result.state == "STARTED":
        return SyncStatus(task_id=task_id, status="started", message="Task is running.")
    if result.state == "SUCCESS":
        return SyncStatus(task_id=task_id, status="success", message=str(result.result))
    if result.state == "FAILURE":
        return SyncStatus(task_id=task_id, status="failure", message=str(result.result))

    return SyncStatus(task_id=task_id, status=result.state, message="Unknown state.")
