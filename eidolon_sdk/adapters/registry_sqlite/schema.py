"""Schema bootstrap and legacy import for the registry SQLite adapter."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .orm import RegistryBase

logger = logging.getLogger(__name__)


async def ensure_registry_schema(
    engine: AsyncEngine,
    *,
    legacy_users_yaml_path: Path | None = None,
) -> None:
    """Create current registry tables and import supported legacy sources."""
    async with engine.begin() as conn:
        await conn.run_sync(RegistryBase.metadata.create_all)
        await _ensure_user_columns(conn)
        await _migrate_legacy_user_metadata(conn)
        if legacy_users_yaml_path is not None:
            await _migrate_legacy_memory_yaml(conn, legacy_users_yaml_path)


async def _ensure_user_columns(conn) -> None:  # type: ignore[no-untyped-def]
    rows = (await conn.execute(text("PRAGMA table_info(users)"))).fetchall()
    columns = {str(row[1]) for row in rows}
    specs = {
        "enabled": "INTEGER NOT NULL DEFAULT 1",
        "palace_path": "TEXT NOT NULL DEFAULT ''",
        "memory_port": "INTEGER NOT NULL DEFAULT 0",
        "consolidator_enabled": "INTEGER NOT NULL DEFAULT 1",
        "consolidator_interval_hours": "REAL NOT NULL DEFAULT 6.0",
        "consolidator_window_days": "INTEGER NOT NULL DEFAULT 30",
        "consolidator_min_drawers": "INTEGER NOT NULL DEFAULT 3",
        "consolidator_min_confidence": "REAL NOT NULL DEFAULT 0.6",
        "created_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, ddl in specs.items():
        if name not in columns:
            await conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))


async def _migrate_legacy_user_metadata(conn) -> None:  # type: ignore[no-untyped-def]
    exists = (
        await conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_metadata'")
        )
    ).fetchone()
    if not exists:
        return

    now = datetime.now(timezone.utc).isoformat()
    rows = (
        await conn.execute(
            text("SELECT user_id, tenant_id, active_agent_id, display_name FROM user_metadata")
        )
    ).fetchall()
    for row in rows:
        await conn.execute(
            text(
                """
                INSERT INTO users (
                    user_id, tenant_id, active_agent_id, display_name,
                    enabled, palace_path, memory_port, consolidator_enabled,
                    consolidator_interval_hours, consolidator_window_days,
                    consolidator_min_drawers, consolidator_min_confidence, created_at
                )
                VALUES (
                    :user_id, :tenant_id, :active_agent_id, :display_name,
                    1, '', 0, 1, 6.0, 30, 3, 0.6, :created_at
                )
                ON CONFLICT(user_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    active_agent_id = excluded.active_agent_id,
                    display_name = excluded.display_name
                """
            ),
            {
                "user_id": row.user_id,
                "tenant_id": row.tenant_id,
                "active_agent_id": row.active_agent_id,
                "display_name": row.display_name or "",
                "created_at": now,
            },
        )


async def _migrate_legacy_memory_yaml(
    conn,  # type: ignore[no-untyped-def]
    yaml_path: Path,
) -> None:
    if not yaml_path.is_file():
        return
    try:
        import yaml

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        logger.warning("failed to read legacy memory users.yaml", exc_info=True)
        return

    now = datetime.now(timezone.utc).isoformat()
    for raw in data.get("users", []) or []:
        if not isinstance(raw, dict):
            continue
        user_id = str(raw.get("id") or "").strip()
        if not user_id:
            continue
        cons = raw.get("consolidator")
        if not isinstance(cons, dict):
            cons = {}
        await conn.execute(
            text(
                """
                INSERT INTO users (
                    user_id, tenant_id, display_name, enabled, palace_path,
                    memory_port, consolidator_enabled,
                    consolidator_interval_hours, consolidator_window_days,
                    consolidator_min_drawers, consolidator_min_confidence, created_at
                )
                VALUES (
                    :user_id, 'default', :display_name, :enabled, :palace_path,
                    :memory_port, :consolidator_enabled,
                    :consolidator_interval_hours, :consolidator_window_days,
                    :consolidator_min_drawers, :consolidator_min_confidence, :created_at
                )
                ON CONFLICT(user_id) DO UPDATE SET
                    enabled = CASE
                        WHEN users.memory_port = 0 THEN excluded.enabled
                        ELSE users.enabled
                    END,
                    palace_path = CASE
                        WHEN users.memory_port = 0 THEN excluded.palace_path
                        ELSE users.palace_path
                    END,
                    memory_port = CASE
                        WHEN users.memory_port = 0 THEN excluded.memory_port
                        ELSE users.memory_port
                    END,
                    consolidator_enabled = CASE
                        WHEN users.memory_port = 0 THEN excluded.consolidator_enabled
                        ELSE users.consolidator_enabled
                    END,
                    consolidator_interval_hours = CASE
                        WHEN users.memory_port = 0 THEN excluded.consolidator_interval_hours
                        ELSE users.consolidator_interval_hours
                    END,
                    consolidator_window_days = CASE
                        WHEN users.memory_port = 0 THEN excluded.consolidator_window_days
                        ELSE users.consolidator_window_days
                    END,
                    consolidator_min_drawers = CASE
                        WHEN users.memory_port = 0 THEN excluded.consolidator_min_drawers
                        ELSE users.consolidator_min_drawers
                    END,
                    consolidator_min_confidence = CASE
                        WHEN users.memory_port = 0 THEN excluded.consolidator_min_confidence
                        ELSE users.consolidator_min_confidence
                    END,
                    created_at = CASE
                        WHEN users.created_at = '' THEN excluded.created_at
                        ELSE users.created_at
                    END
                """
            ),
            {
                "user_id": user_id,
                "display_name": user_id,
                "enabled": 1 if bool(raw.get("enabled", True)) else 0,
                "palace_path": str(raw.get("palace_path") or ""),
                "memory_port": int(raw.get("port", 0) or 0),
                "consolidator_enabled": 1 if bool(cons.get("enabled", True)) else 0,
                "consolidator_interval_hours": float(
                    cons.get("interval_hours", 6.0) or 6.0
                ),
                "consolidator_window_days": int(cons.get("window_days", 30) or 30),
                "consolidator_min_drawers": int(cons.get("min_drawers", 3) or 3),
                "consolidator_min_confidence": float(
                    cons.get("min_confidence", 0.6) or 0.6
                ),
                "created_at": now,
            },
        )
