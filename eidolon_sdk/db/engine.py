"""SQLAlchemy v2 async SQLite engine helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.event import listens_for
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from .settings import SqliteSettings


def _build_sqlite_url(path: Path | str) -> tuple[str, bool]:
    path_str = str(path)
    if path_str == ":memory:":
        return "sqlite+aiosqlite:///:memory:", True
    expanded = Path(path_str).expanduser()
    expanded.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{expanded}", False


def create_sqlite_engine(settings: SqliteSettings) -> AsyncEngine:
    """Create an async SQLite engine with Eidolon-standard PRAGMAs."""
    url, in_memory = _build_sqlite_url(settings.path)
    kwargs: dict = {"future": True, "echo": False}
    if in_memory:
        kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        kwargs.update(poolclass=NullPool)
    engine = create_async_engine(url, **kwargs)

    @listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA foreign_keys = ON")
            cur.execute(f"PRAGMA busy_timeout = {settings.busy_timeout_ms}")
            if settings.enable_wal and not in_memory:
                cur.execute("PRAGMA journal_mode = WAL")
            cur.execute(f"PRAGMA synchronous = {settings.synchronous}")
        finally:
            cur.close()

    return engine


def create_sqlite_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
