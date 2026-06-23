"""Schema bootstrap for the registry SQLite adapter."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .orm import RegistryBase

async def ensure_registry_schema(engine: AsyncEngine) -> None:
    """Create current registry tables and import supported legacy SQLite sources."""
    async with engine.begin() as conn:
        await conn.run_sync(RegistryBase.metadata.create_all)
        await _ensure_user_columns(conn)
        await _migrate_legacy_user_metadata(conn)


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
