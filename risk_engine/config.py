"""Load the main settings file (config/settings.yaml)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS = PROJECT_ROOT / "config" / "settings.yaml"


class ConfigError(Exception):
    """A settings or pack file is missing or wrong."""


def load_settings(path: Path | str | None = None) -> dict:
    path = Path(path) if path else DEFAULT_SETTINGS
    if not path.exists():
        raise ConfigError(f"Settings file not found: {path}")
    with open(path, encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}
    for key in ("models", "pricing", "budget", "estimate", "simulation"):
        if key not in settings:
            raise ConfigError(f"Settings file {path} is missing the '{key}' section.")
    return settings


def resolve_path(relative: str) -> Path:
    """Paths in settings are relative to the project folder."""
    p = Path(relative)
    return p if p.is_absolute() else PROJECT_ROOT / p


def api_key_present(settings: dict) -> bool:
    """True if the API key environment variable is set. Never returns the key."""
    return bool(os.environ.get(settings.get("api_key_env_var", "ANTHROPIC_API_KEY")))
