from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from eidolon_sdk.adapters.registry_sqlite import (
    RegistrySqliteStore,
    TenantRepository,
    UserRepository,
)
from eidolon_sdk.registry.models import (
    ConsolidatorConfig,
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


async def test_legacy_memory_yaml_import_preserves_explicit_registry_config(tmp_path) -> None:
    db = tmp_path / "registry.sqlite3"
    yaml_path = tmp_path / "users.yaml"
    yaml_path.write_text(
        """
users:
  - id: alice
    enabled: false
    palace_path: /legacy/alice
    port: 8033
    consolidator:
      enabled: false
      interval_hours: 2
      window_days: 5
      min_drawers: 2
      min_confidence: 0.8
""",
        encoding="utf-8",
    )

    repo = UserRepository(RegistrySqliteStore(db, legacy_users_yaml_path=yaml_path))
    fetched = await repo.get("alice")
    assert fetched is not None
    assert fetched.display_name == "alice"
    assert fetched.enabled is False
    assert fetched.palace_path == "/legacy/alice"
    assert fetched.memory_port == 8033
    assert fetched.consolidator.interval_hours == 2

    await repo.put(
        UserRegistryRecord(
            user_id="alice",
            display_name="Alice",
            enabled=True,
            palace_path="/explicit/alice",
            memory_port=8044,
        )
    )
    await store_reopen_and_get(db, yaml_path)


async def store_reopen_and_get(db, yaml_path) -> None:  # type: ignore[no-untyped-def]
    repo = UserRepository(RegistrySqliteStore(db, legacy_users_yaml_path=yaml_path))
    fetched = await repo.get("alice")
    assert fetched is not None
    assert fetched.display_name == "Alice"
    assert fetched.enabled is True
    assert fetched.palace_path == "/explicit/alice"
    assert fetched.memory_port == 8044

