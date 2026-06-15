from __future__ import annotations

from sqlalchemy import text

from eidolon_sdk.adapters.registry_sqlite.schema import ensure_registry_schema
from eidolon_sdk.db.engine import create_sqlite_engine
from eidolon_sdk.db.health import integrity_check, quick_check
from eidolon_sdk.db.settings import SqliteSettings


async def test_file_db_pragmas_and_health(tmp_path) -> None:
    engine = create_sqlite_engine(
        SqliteSettings(path=tmp_path / "registry.sqlite3", busy_timeout_ms=1234)
    )
    try:
        async with engine.connect() as conn:
            foreign_keys = await conn.scalar(text("PRAGMA foreign_keys"))
            busy_timeout = await conn.scalar(text("PRAGMA busy_timeout"))
            journal_mode = await conn.scalar(text("PRAGMA journal_mode"))
        assert foreign_keys == 1
        assert busy_timeout == 1234
        assert str(journal_mode).lower() == "wal"
        assert await quick_check(engine) == "ok"
        assert await integrity_check(engine) == "ok"
    finally:
        await engine.dispose()


async def test_memory_db_bootstrap_is_idempotent() -> None:
    engine = create_sqlite_engine(SqliteSettings(path=":memory:"))
    try:
        await ensure_registry_schema(engine)
        await ensure_registry_schema(engine)
        async with engine.connect() as conn:
            tables = {
                row[0]
                for row in (
                    await conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table'")
                    )
                ).fetchall()
            }
        assert {"tenants", "users"}.issubset(tables)
    finally:
        await engine.dispose()

