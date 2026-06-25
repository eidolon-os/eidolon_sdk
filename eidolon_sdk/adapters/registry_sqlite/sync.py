"""Synchronous read helpers for registry SQLite.

Most registry access should use the async repositories in ``repositories.py``.
These helpers exist for operational code paths that are intentionally sync,
such as process discovery/status pages.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from eidolon_sdk.biz.registry.models import ConsolidatorConfig, UserRegistryRecord


def list_user_records_sync(db_path: str | Path) -> dict[str, UserRegistryRecord]:
    """Read all users from a registry SQLite DB.

    Returns an empty mapping when the DB or ``users`` table is unavailable,
    matching the fault-tolerant behavior expected by admin status surfaces.
    """
    path = Path(db_path).expanduser()
    if not path.exists():
        return {}
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        with conn:
            rows = conn.execute("SELECT * FROM users ORDER BY user_id").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        if conn is not None:
            conn.close()

    return {row["user_id"]: _user_from_row(row) for row in rows}


def list_memory_user_records_sync(db_path: str | Path) -> list[UserRegistryRecord]:
    """Return users configured with a memory runner port."""
    return [
        record
        for record in list_user_records_sync(db_path).values()
        if int(record.memory_port or 0) > 0
    ]


def _user_from_row(row: sqlite3.Row) -> UserRegistryRecord:
    keys = set(row.keys())

    def val(name: str, default=None):
        return row[name] if name in keys else default

    return UserRegistryRecord(
        user_id=row["user_id"],
        tenant_id=val("tenant_id", "default"),
        active_agent_id=val("active_agent_id"),
        display_name=val("display_name", "") or "",
        enabled=bool(val("enabled", 1)),
        palace_path=val("palace_path", "") or "",
        memory_port=int(val("memory_port", 0) or 0),
        consolidator=ConsolidatorConfig(
            enabled=bool(val("consolidator_enabled", 1)),
            interval_hours=float(val("consolidator_interval_hours", 6.0) or 6.0),
            window_days=int(val("consolidator_window_days", 30) or 30),
            min_drawers=int(val("consolidator_min_drawers", 3) or 3),
            min_confidence=float(val("consolidator_min_confidence", 0.6) or 0.6),
        ),
        created_at=val("created_at", "") or "",
    )


__all__ = ["list_memory_user_records_sync", "list_user_records_sync"]
