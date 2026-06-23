"""SQLite repository implementations for registry stores."""

from __future__ import annotations

import json
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
    AgentMetadataRecord,
    ConsolidatorConfig,
    DeviceBindingRecord,
    DeviceRegistryRecord,
    TenantSpec,
    UserRegistryRecord,
)
from eidolon_sdk.registry.settings import resolve_registry_db_path

from .orm import AgentMetadataRow, DeviceBindingRow, DeviceRow, TenantRow, UserRow
from .schema import ensure_registry_schema

AUTO_PORT_MIN = 8030
AUTO_PORT_MAX = 8100


class RegistrySqliteStore:
    """Shared SQLite engine/session owner for registry repositories."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        settings: SqliteSettings | None = None,
    ) -> None:
        resolved_db_path = db_path if db_path is not None else resolve_registry_db_path()
        self.db_path = (
            Path(resolved_db_path).expanduser()
            if str(resolved_db_path) != ":memory:"
            else Path(":memory:")
        )
        self._settings = settings or SqliteSettings(path=resolved_db_path)
        self._engine = create_sqlite_engine(self._settings)
        self._session_factory = create_sqlite_session_factory(self._engine)
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
        await ensure_registry_schema(self._engine)
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


class DeviceRepository:
    """SQLAlchemy-backed hub device registry store."""

    def __init__(self, store: RegistrySqliteStore) -> None:
        self._store = store

    async def get(self, device_id: str) -> DeviceRegistryRecord | None:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            row = await session.get(DeviceRow, device_id)
            if row is None:
                return None
            return _device_from_row(row)

    async def put(self, record: DeviceRegistryRecord) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            row = await session.get(DeviceRow, record.device_id)
            if row is None:
                session.add(_device_to_row(record))
                return
            _apply_device_record(row, record)

    async def delete(self, device_id: str) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            await session.execute(delete(DeviceRow).where(DeviceRow.device_id == device_id))

    async def list_all(self) -> dict[str, DeviceRegistryRecord]:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            rows = (
                await session.execute(select(DeviceRow).order_by(DeviceRow.device_id))
            ).scalars()
            return {row.device_id: _device_from_row(row) for row in rows}


class DeviceBindingRepository:
    """SQLAlchemy-backed admin device-to-agent binding store."""

    def __init__(self, store: RegistrySqliteStore) -> None:
        self._store = store

    async def get(self, device_id: str) -> DeviceBindingRecord | None:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            row = await session.get(DeviceBindingRow, device_id)
            if row is None:
                return None
            return _device_binding_from_row(row)

    async def put(self, record: DeviceBindingRecord) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            row = await session.get(DeviceBindingRow, record.device_id)
            if row is None:
                session.add(_device_binding_to_row(record))
                return
            row.agent_id = record.agent_id
            row.bound_at = record.bound_at
            row.interaction_mode = record.interaction_mode

    async def delete(self, device_id: str) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            await session.execute(
                delete(DeviceBindingRow).where(DeviceBindingRow.device_id == device_id)
            )

    async def list_all(self) -> dict[str, DeviceBindingRecord]:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            rows = (
                await session.execute(select(DeviceBindingRow).order_by(DeviceBindingRow.device_id))
            ).scalars()
            return {row.device_id: _device_binding_from_row(row) for row in rows}

    async def list_by_agent(self, agent_id: str) -> list[str]:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            rows = (
                await session.execute(
                    select(DeviceBindingRow.device_id)
                    .where(DeviceBindingRow.agent_id == agent_id)
                    .order_by(DeviceBindingRow.device_id)
                )
            ).scalars()
            return list(rows)


class AgentMetadataRepository:
    """SQLAlchemy-backed admin agent metadata store."""

    def __init__(self, store: RegistrySqliteStore) -> None:
        self._store = store

    async def get(self, agent_id: str) -> AgentMetadataRecord | None:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            row = await session.get(AgentMetadataRow, agent_id)
            if row is None:
                return None
            return _agent_metadata_from_row(row)

    async def put(self, record: AgentMetadataRecord) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            row = await session.get(AgentMetadataRow, record.agent_id)
            if row is None:
                session.add(_agent_metadata_to_row(record))
                return
            row.tenant_id = record.tenant_id
            row.user_id = record.user_id
            row.template_id = record.template_id
            row.template_revision = record.template_revision
            row.display_name = record.display_name
            row.created_at = record.created_at

    async def delete(self, agent_id: str) -> None:
        await self._store.ensure_schema()
        async with session_scope(self._store.session_factory) as session:
            await session.execute(
                delete(AgentMetadataRow).where(AgentMetadataRow.agent_id == agent_id)
            )

    async def list_all(self) -> dict[str, AgentMetadataRecord]:
        await self._store.ensure_schema()
        async with self._store.session_factory() as session:
            rows = (
                await session.execute(select(AgentMetadataRow).order_by(AgentMetadataRow.agent_id))
            ).scalars()
            return {row.agent_id: _agent_metadata_from_row(row) for row in rows}

    async def list_by_user(self, user_id: str) -> list[tuple[str, AgentMetadataRecord]]:
        all_meta = await self.list_all()
        return [(agent_id, meta) for agent_id, meta in all_meta.items() if meta.user_id == user_id]


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


def _metadata_from_json(raw: str) -> dict:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _metadata_to_json(data: dict) -> str:
    return json.dumps(data or {}, ensure_ascii=False, sort_keys=True)


def _device_from_row(row: DeviceRow) -> DeviceRegistryRecord:
    return DeviceRegistryRecord(
        device_id=row.device_id,
        name=row.name or "",
        kind=row.kind or "unknown",
        enabled=bool(row.enabled),
        psk_hash=row.psk_hash,
        paired=bool(row.paired),
        approved=bool(row.approved),
        approved_at=row.approved_at,
        created_at=row.created_at or "",
        last_seen=row.last_seen or "",
        metadata=_metadata_from_json(row.metadata_json),
    )


def _device_to_row(record: DeviceRegistryRecord) -> DeviceRow:
    return DeviceRow(
        device_id=record.device_id,
        name=record.name,
        kind=record.kind,
        enabled=1 if record.enabled else 0,
        psk_hash=record.psk_hash,
        paired=1 if record.paired else 0,
        approved=1 if record.approved else 0,
        approved_at=record.approved_at,
        created_at=record.created_at,
        last_seen=record.last_seen,
        metadata_json=_metadata_to_json(record.metadata),
    )


def _apply_device_record(row: DeviceRow, record: DeviceRegistryRecord) -> None:
    row.name = record.name
    row.kind = record.kind
    row.enabled = 1 if record.enabled else 0
    row.psk_hash = record.psk_hash
    row.paired = 1 if record.paired else 0
    row.approved = 1 if record.approved else 0
    row.approved_at = record.approved_at
    row.created_at = record.created_at
    row.last_seen = record.last_seen
    row.metadata_json = _metadata_to_json(record.metadata)


def _device_binding_from_row(row: DeviceBindingRow) -> DeviceBindingRecord:
    return DeviceBindingRecord(
        device_id=row.device_id,
        agent_id=row.agent_id,
        bound_at=row.bound_at,
        interaction_mode=row.interaction_mode,
    )


def _device_binding_to_row(record: DeviceBindingRecord) -> DeviceBindingRow:
    return DeviceBindingRow(
        device_id=record.device_id,
        agent_id=record.agent_id,
        bound_at=record.bound_at,
        interaction_mode=record.interaction_mode,
    )


def _agent_metadata_from_row(row: AgentMetadataRow) -> AgentMetadataRecord:
    return AgentMetadataRecord(
        agent_id=row.agent_id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        template_id=row.template_id,
        template_revision=int(row.template_revision or 1),
        display_name=row.display_name or "",
        created_at=row.created_at or "",
    )


def _agent_metadata_to_row(record: AgentMetadataRecord) -> AgentMetadataRow:
    return AgentMetadataRow(
        agent_id=record.agent_id,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        template_id=record.template_id,
        template_revision=record.template_revision,
        display_name=record.display_name,
        created_at=record.created_at,
    )
