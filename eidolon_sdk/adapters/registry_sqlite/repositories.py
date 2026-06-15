"""SQLite repository implementations for registry stores."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from eidolon_sdk.db.engine import (
    create_sqlite_engine,
    create_sqlite_session_factory,
    session_scope,
)
from eidolon_sdk.db.settings import SqliteSettings
from eidolon_sdk.registry.models import (
    ConsolidatorConfig,
    TenantSpec,
    UserRegistryRecord,
)

from .orm import TenantRow, UserRow
from .schema import ensure_registry_schema

AUTO_PORT_MIN = 8030
AUTO_PORT_MAX = 8100


class RegistrySqliteStore:
    """Shared SQLite engine/session owner for registry repositories."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        legacy_users_yaml_path: Path | None = None,
        settings: SqliteSettings | None = None,
    ) -> None:
        self.db_path = Path(db_path).expanduser() if str(db_path) != ":memory:" else Path(":memory:")
        self._settings = settings or SqliteSettings(path=db_path)
        self._engine = create_sqlite_engine(self._settings)
        self._session_factory = create_sqlite_session_factory(self._engine)
        self._legacy_users_yaml_path = legacy_users_yaml_path
        self._schema_ready = False

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        await ensure_registry_schema(
            self._engine,
            legacy_users_yaml_path=self._legacy_users_yaml_path,
        )
        self._schema_ready = True

    async def dispose(self) -> None:
        await self._engine.dispose()


class TenantRepository:
    """SQLAlchemy-backed tenant store."""

    def __init__(self, store: RegistrySqliteStore) -> None:
        self._store = store

    async def get(self, tenant_id: str) -> TenantSpec | None:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            row = await session.get(TenantRow, tenant_id)
            if row is None:
                return None
            return _tenant_from_row(row)

    async def put(self, spec: TenantSpec) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            row = await session.get(TenantRow, spec.tenant_id)
            if row is None:
                session.add(
                    TenantRow(
                        tenant_id=spec.tenant_id,
                        display_name=spec.display_name,
                        created_at=spec.created_at.isoformat(),
                    )
                )
                return
            row.display_name = spec.display_name
            row.created_at = spec.created_at.isoformat()

    async def delete(self, tenant_id: str) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            await session.execute(delete(TenantRow).where(TenantRow.tenant_id == tenant_id))

    async def list_all(self) -> list[TenantSpec]:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            rows = (
                await session.execute(select(TenantRow).order_by(TenantRow.tenant_id))
            ).scalars()
            return [_tenant_from_row(row) for row in rows]

    async def count(self) -> int:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            n = await session.scalar(select(func.count()).select_from(TenantRow))
            return int(n or 0)


class UserRepository:
    """SQLAlchemy-backed user registry store."""

    def __init__(
        self,
        store: RegistrySqliteStore,
        *,
        auto_port_min: int = AUTO_PORT_MIN,
        auto_port_max: int = AUTO_PORT_MAX,
    ) -> None:
        self._store = store
        self._auto_port_min = auto_port_min
        self._auto_port_max = auto_port_max

    async def get(self, user_id: str) -> UserRegistryRecord | None:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            row = await session.get(UserRow, user_id)
            if row is None:
                return None
            return _user_from_row(row)

    async def put(self, record: UserRegistryRecord) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            row = await session.get(UserRow, record.user_id)
            if row is None:
                session.add(_user_to_row(record))
                return
            _apply_user_record(row, record)

    async def delete(self, user_id: str) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            await session.execute(delete(UserRow).where(UserRow.user_id == user_id))

    async def list_all(self) -> dict[str, UserRegistryRecord]:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            rows = (
                await session.execute(select(UserRow).order_by(UserRow.user_id))
            ).scalars()
            return {row.user_id: _user_from_row(row) for row in rows}

    async def allocate_memory_port(self) -> int:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            ports = (
                await session.execute(select(UserRow.memory_port).where(UserRow.memory_port > 0))
            ).scalars()
            taken = {int(port) for port in ports}
        for port in range(self._auto_port_min, self._auto_port_max):
            if port not in taken:
                return port
        raise RuntimeError(
            f"no free memory port in [{self._auto_port_min}, {self._auto_port_max})"
        )


def _tenant_from_row(row: TenantRow) -> TenantSpec:
    return TenantSpec(
        tenant_id=row.tenant_id,
        display_name=row.display_name,
        created_at=_parse_dt(row.created_at),
    )


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _user_from_row(row: UserRow) -> UserRegistryRecord:
    return UserRegistryRecord(
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        active_agent_id=row.active_agent_id,
        display_name=row.display_name or "",
        enabled=bool(row.enabled),
        palace_path=row.palace_path or "",
        memory_port=int(row.memory_port or 0),
        consolidator=ConsolidatorConfig(
            enabled=bool(row.consolidator_enabled),
            interval_hours=float(row.consolidator_interval_hours or 6.0),
            window_days=int(row.consolidator_window_days or 30),
            min_drawers=int(row.consolidator_min_drawers or 3),
            min_confidence=float(row.consolidator_min_confidence or 0.6),
        ),
        created_at=row.created_at or "",
    )


def _user_to_row(record: UserRegistryRecord) -> UserRow:
    return UserRow(
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        active_agent_id=record.active_agent_id,
        display_name=record.display_name,
        enabled=1 if record.enabled else 0,
        palace_path=record.palace_path,
        memory_port=record.memory_port,
        consolidator_enabled=1 if record.consolidator.enabled else 0,
        consolidator_interval_hours=record.consolidator.interval_hours,
        consolidator_window_days=record.consolidator.window_days,
        consolidator_min_drawers=record.consolidator.min_drawers,
        consolidator_min_confidence=record.consolidator.min_confidence,
        created_at=record.created_at,
    )


def _apply_user_record(row: UserRow, record: UserRegistryRecord) -> None:
    row.tenant_id = record.tenant_id
    row.active_agent_id = record.active_agent_id
    row.display_name = record.display_name
    row.enabled = 1 if record.enabled else 0
    row.palace_path = record.palace_path
    row.memory_port = record.memory_port
    row.consolidator_enabled = 1 if record.consolidator.enabled else 0
    row.consolidator_interval_hours = record.consolidator.interval_hours
    row.consolidator_window_days = record.consolidator.window_days
    row.consolidator_min_drawers = record.consolidator.min_drawers
    row.consolidator_min_confidence = record.consolidator.min_confidence
    if record.created_at:
        row.created_at = record.created_at

