from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from eidolon_sdk.adapters.registry_sqlite import (
    AgentMetadataRepository,
    DeviceBindingRepository,
    DeviceRepository,
    RegistrySqliteStore,
    TenantRepository,
    UserRepository,
)
from eidolon_sdk.registry.models import (
    AgentMetadataRecord,
    ConsolidatorConfig,
    DeviceBindingRecord,
    DeviceRegistryRecord,
    TenantSpec,
    UserRegistryRecord,
)


async def test_tenant_repository_crud(tmp_path) -> None:
    store = RegistrySqliteStore(tmp_path / "registry.sqlite3")
    repo = TenantRepository(store)
    now = datetime.now(timezone.utc)

    assert await repo.get("missing") is None
    await repo.put(TenantSpec(tenant_id="a", display_name="A", created_at=now))
    await repo.put(
        TenantSpec(
            tenant_id="b",
            display_name="B",
            created_at=now + timedelta(seconds=1),
        )
    )

    assert (await repo.get("a")).display_name == "A"  # type: ignore[union-attr]
    assert await repo.count() == 2
    assert [tenant.tenant_id for tenant in await repo.list_all()] == ["a", "b"]

    await repo.delete("a")
    await repo.delete("a")
    assert await repo.get("a") is None


async def test_user_repository_round_trip_and_port_allocation(tmp_path) -> None:
    store = RegistrySqliteStore(tmp_path / "registry.sqlite3")
    repo = UserRepository(store)

    record = UserRegistryRecord(
        user_id="alice",
        tenant_id="default",
        active_agent_id="ag-1",
        display_name="Alice",
        enabled=False,
        palace_path="/tmp/alice",
        memory_port=8030,
        consolidator=ConsolidatorConfig(
            enabled=False,
            interval_hours=3.5,
            window_days=7,
            min_drawers=2,
            min_confidence=0.75,
        ),
        created_at="2026-06-15T00:00:00+00:00",
    )

    assert await repo.get("alice") is None
    await repo.put(record)
    fetched = await repo.get("alice")
    assert fetched == record
    assert await repo.list_all() == {"alice": record}
    assert await repo.allocate_memory_port() == 8031

    await repo.delete("alice")
    assert await repo.get("alice") is None


async def test_user_repository_port_exhaustion(tmp_path) -> None:
    store = RegistrySqliteStore(tmp_path / "registry.sqlite3")
    repo = UserRepository(store, auto_port_min=1, auto_port_max=3)
    await repo.put(UserRegistryRecord(user_id="a", memory_port=1))
    await repo.put(UserRegistryRecord(user_id="b", memory_port=2))

    with pytest.raises(RuntimeError, match="no free memory port"):
        await repo.allocate_memory_port()


async def test_legacy_user_metadata_table_imports(tmp_path) -> None:
    db = tmp_path / "registry.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE user_metadata (
                user_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                active_agent_id TEXT,
                display_name TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO user_metadata
            (user_id, tenant_id, active_agent_id, display_name)
            VALUES ('alice', 'default', 'ag-1', 'Alice')
            """
        )

    repo = UserRepository(RegistrySqliteStore(db))
    fetched = await repo.get("alice")
    assert fetched is not None
    assert fetched.tenant_id == "default"
    assert fetched.active_agent_id == "ag-1"
    assert fetched.display_name == "Alice"
    assert fetched.created_at


async def test_device_repository_round_trip(tmp_path) -> None:
    repo = DeviceRepository(RegistrySqliteStore(tmp_path / "registry.sqlite3"))
    record = DeviceRegistryRecord(
        device_id="1c:db:d4:7a:ef:0c",
        name="Desk",
        kind="esp32",
        enabled=True,
        paired=False,
        approved=False,
        created_at="2026-06-23T00:00:00+00:00",
        last_seen="2026-06-23T00:01:00+00:00",
        metadata={"fingerprint": "abc", "recent_nonces": ["n1"]},
    )

    assert await repo.get(record.device_id) is None
    await repo.put(record)
    assert await repo.get(record.device_id) == record
    assert await repo.list_all() == {record.device_id: record}

    updated = record.model_copy(update={"approved": True, "approved_at": "2026-06-23T00:02:00+00:00"})
    await repo.put(updated)
    assert await repo.get(record.device_id) == updated

    await repo.delete(record.device_id)
    assert await repo.get(record.device_id) is None


async def test_device_binding_repository_round_trip(tmp_path) -> None:
    repo = DeviceBindingRepository(RegistrySqliteStore(tmp_path / "registry.sqlite3"))
    binding = DeviceBindingRecord(
        device_id="1c:db:d4:7a:ef:0c",
        agent_id="ag-1",
        bound_at="2026-06-23T00:00:00+00:00",
        interaction_mode="half_duplex",
    )

    await repo.put(binding)
    assert await repo.get(binding.device_id) == binding
    assert await repo.list_all() == {binding.device_id: binding}
    assert await repo.list_by_agent("ag-1") == [binding.device_id]
    assert await repo.list_by_agent("ag-2") == []

    await repo.delete(binding.device_id)
    assert await repo.get(binding.device_id) is None


async def test_agent_metadata_repository_round_trip(tmp_path) -> None:
    repo = AgentMetadataRepository(RegistrySqliteStore(tmp_path / "registry.sqlite3"))
    meta = AgentMetadataRecord(
        agent_id="ag-1",
        tenant_id="default",
        user_id="alice",
        template_id="caretaker",
        template_revision=2,
        display_name="A1",
        created_at="2026-06-23T00:00:00+00:00",
    )

    await repo.put(meta)
    assert await repo.get("ag-1") == meta
    assert await repo.list_all() == {"ag-1": meta}
    assert await repo.list_by_user("alice") == [("ag-1", meta)]
    assert await repo.list_by_user("bob") == []

    await repo.delete("ag-1")
    assert await repo.get("ag-1") is None


async def test_registry_store_shares_control_plane_tables(tmp_path) -> None:
    store = RegistrySqliteStore(tmp_path / "registry.sqlite3")
    users = UserRepository(store)
    devices = DeviceRepository(store)
    bindings = DeviceBindingRepository(store)

    await users.put(UserRegistryRecord(user_id="alice", tenant_id="default"))
    await devices.put(
        DeviceRegistryRecord(
            device_id="dev-1",
            created_at="2026-06-23T00:00:00+00:00",
            last_seen="2026-06-23T00:00:00+00:00",
        )
    )
    await bindings.put(
        DeviceBindingRecord(
            device_id="dev-1",
            agent_id="ag-1",
            bound_at="2026-06-23T00:00:00+00:00",
        )
    )

    assert "alice" in await users.list_all()
    assert "dev-1" in await devices.list_all()
    assert "dev-1" in await bindings.list_all()
