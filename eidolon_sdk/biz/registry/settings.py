"""Shared registry path resolution.

The registry DB is a cross-project control-plane store. Keep path precedence
centralized here so admin, hub, and operational helpers do not drift.
"""

from __future__ import annotations

import os
from pathlib import Path

REGISTRY_DB_ENV = "EIDOLON_REGISTRY_DB_PATH"


def default_registry_db_path() -> Path:
    """Return the canonical registry DB path."""
    state_root = Path(os.environ.get("EIDOLON_STATE_ROOT", "~/eidolon/data")).expanduser()
    return state_root / "registry/registry.sqlite3"


def resolve_registry_db_path(
    explicit: str | Path | None = None,
) -> Path:
    """Resolve the shared registry path.

    Precedence:
      1. canonical ``EIDOLON_REGISTRY_DB_PATH``;
      2. explicit config value, such as YAML;
      3. ``$EIDOLON_STATE_ROOT/registry/registry.sqlite3`` (the Mac profile
         defaults the state root to ``~/eidolon/data``).
    """
    raw = os.environ.get(REGISTRY_DB_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    if explicit is not None and str(explicit).strip():
        return Path(explicit).expanduser()
    return default_registry_db_path()


__all__ = [
    "REGISTRY_DB_ENV",
    "default_registry_db_path",
    "resolve_registry_db_path",
]
