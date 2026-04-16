"""
api/routes/setup.py – First-run configuration UI backend.

GET  /api/v1/setup  – Return current non-infrastructure settings. Sensitive
                      values are masked; the response includes a has_value flag
                      so the UI can show "already configured" without revealing keys.
POST /api/v1/setup  – Write settings to /config/settings.env (persisted on a
                      Docker volume) and reload the settings cache.
                      Services pick up the new values immediately — no restart needed.
"""

from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings, reset_settings

logger = structlog.get_logger(__name__)
router = APIRouter()

CONFIG_FILE = Path("/config/settings.env")

# Keys the setup UI can configure. Infrastructure vars (DATABASE_URL, SECRET_KEY,
# Redis URLs) must still be supplied via Portainer / os env — they are excluded here.
CONFIGURABLE = {
    "llm_provider",
    "openai_api_key",
    "gemini_api_key",
    "openai_chat_model",
    "gemini_chat_model",
    "radarr_url",
    "radarr_api_key",
    "plex_url",
    "plex_token",
    "tmdb_api_key",
    "tmdb_access_token",
    "overseerr_url",
    "overseerr_api_key",
    "app_env",
    "log_level",
    "discovery_threshold",
    "vector_distance_cutoff",
    "feedback_few_shot_count",
}

SENSITIVE = {
    "openai_api_key",
    "gemini_api_key",
    "plex_token",
    "radarr_api_key",
    "tmdb_api_key",
    "tmdb_access_token",
    "overseerr_api_key",
}

_MASK = "••••••••"


class SetupPayload(BaseModel):
    settings: dict[str, Any]


@router.get("/setup", summary="Get current configuration state")
def get_setup():
    """
    Returns the current configuration state for the setup UI.
    Sensitive fields return a masked value with a `has_value` boolean.
    `is_configured` is true when all minimum required services are set.
    """
    s = get_settings()
    result: dict[str, Any] = {}

    for key in CONFIGURABLE:
        raw = getattr(s, key, None)
        val = str(raw) if raw is not None else ""
        if key in SENSITIVE:
            result[key] = {"value": _MASK if val else "", "has_value": bool(val)}
        else:
            result[key] = {"value": val, "has_value": bool(val)}

    llm_ok = bool(
        (s.llm_provider == "openai" and s.openai_api_key)
        or (s.llm_provider == "gemini" and s.gemini_api_key)
    )
    result["is_configured"] = bool(
        s.radarr_url and s.plex_url and s.tmdb_api_key and s.overseerr_url and llm_ok
    )
    return result


@router.post("/setup", summary="Save configuration")
def save_setup(payload: SetupPayload):
    """
    Persist configurable settings to /config/settings.env on the mounted Docker
    volume and reload the settings cache. Services will use the new values on
    the next request — no container restart needed.
    """
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config file so we can merge (preserves values not in payload)
    existing: dict[str, str] = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            existing[k.strip().lower()] = v.strip().strip('"')

    for key, value in payload.settings.items():
        key = key.lower()
        if key not in CONFIGURABLE:
            continue
        str_val = str(value).strip() if value is not None else ""
        # Skip masked sentinel – user left a sensitive field untouched
        if key in SENSITIVE and str_val == _MASK:
            continue
        if str_val:
            existing[key] = str_val
        elif key in existing:
            del existing[key]  # empty string = remove the entry

    lines = ["# VibeCheck runtime configuration – managed by the /setup UI", ""]
    for k, v in existing.items():
        escaped = v.replace('"', '\\"')
        lines.append(f'{k.upper()}="{escaped}"')
    CONFIG_FILE.write_text("\n".join(lines) + "\n")

    reset_settings()
    logger.info("Configuration saved via setup UI", keys=list(existing.keys()))
    return {
        "status": "saved",
        "message": "Configuration saved. Services will use new values on the next request.",
    }
