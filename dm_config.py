"""Config management — reads/writes ~/.virtualdm/config.json.

Called before server starts. Sets os.environ so the rest of the app
works unchanged. Falls back to .env for dev.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".virtualdm"
CONFIG_FILE = CONFIG_DIR / "config.json"

REQUIRED_KEYS = ["anthropic_key", "supabase_url", "supabase_service_key", "connector_secret"]

_ENV_MAP = {
    "anthropic_key": "ANTHROPIC_API_KEY",
    "openai_key": "OPENAI_API_KEY",
    "supabase_url": "SUPABASE_URL",
    "supabase_service_key": "SUPABASE_SERVICE_KEY",
    "connector_secret": "CONNECTOR_SECRET",
    "default_campaign_id": "DEFAULT_CAMPAIGN_ID",
    "rules_edition": "RULES_EDITION",
    "player1_name": "PLAYER1_NAME",
    "player2_name": "PLAYER2_NAME",
}


def load() -> dict:
    """Load config from ~/.virtualdm/config.json and apply to os.environ."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}
    for key, env_var in _ENV_MAP.items():
        val = cfg.get(key)
        if val and not os.environ.get(env_var):
            os.environ[env_var] = str(val)
    return cfg


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = {}
    if CONFIG_FILE.exists():
        try:
            existing = json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    existing.update({k: v for k, v in data.items() if v})
    CONFIG_FILE.write_text(json.dumps(existing, indent=2))
    CONFIG_FILE.chmod(0o600)


def is_configured() -> bool:
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    # Also accept env vars (dev mode with .env)
    return all(
        cfg.get(k) or os.environ.get(_ENV_MAP[k])
        for k in REQUIRED_KEYS
    )


def get(key: str, default: str = "") -> str:
    env_var = _ENV_MAP.get(key)
    if env_var:
        val = os.environ.get(env_var, "")
        if val:
            return val
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text()).get(key, default)
        except Exception:
            pass
    return default
