from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eidolon_sdk.biz.body import (
    CapabilityManifest,
    OwnerDeviceBlackboardSnapshot,
    RuntimeDeviceEntry,
    capability_manifest_revision,
    owner_device_blackboard_key,
)


def _entry(device_id: str, *, companion_id: str, visibility: str = "owner"):
    now = datetime.now(UTC)
    manifest = CapabilityManifest.model_validate(
        {
            "capabilities": [
                {
                    "name": "device.roll_call",
                    "version": 1,
                    "description": "Play the local roll-call response",
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    "result_schema": {"type": "object", "properties": {}},
                }
            ]
        }
    )
    return RuntimeDeviceEntry(
        device_id=device_id,
        registration_id=f"reg-{device_id}",
        provider_companion_id=companion_id,
        provider_companion_name=f"Companion {companion_id}",
        name=device_id,
        visibility=visibility,
        capabilities=manifest.capabilities,
        manifest_revision=capability_manifest_revision(manifest),
        status="online",
        registered_at=now,
        last_seen_at=now,
        lease_expires_at=now + timedelta(seconds=30),
    )


def test_owner_key_is_stable_opaque_and_nats_safe():
    first = owner_device_blackboard_key("owner:1")
    assert first == owner_device_blackboard_key("owner:1")
    assert first != owner_device_blackboard_key("owner:2")
    assert "owner:1" not in first
    assert first.startswith("owner.") and first.endswith(".current")


def test_capability_supports_discovery_and_exact_execution_lookup():
    entry = _entry("guard", companion_id="guard")

    assert entry.capability("device.roll_call") is not None
    assert entry.capability("device.roll_call", 1) is not None
    assert entry.capability("device.roll_call", 2) is None


def test_snapshot_round_trip_and_companion_visibility():
    now = datetime.now(UTC)
    snapshot = OwnerDeviceBlackboardSnapshot(
        owner_id="owner-1",
        epoch="epoch-1",
        revision=1,
        ready=True,
        hub_lease_expires_at=now + timedelta(seconds=30),
        updated_at=now,
        devices={
            "shared": _entry("shared", companion_id="guard"),
            "private": _entry("private", companion_id="guard", visibility="bound_companion"),
        },
    )
    restored = OwnerDeviceBlackboardSnapshot.from_bytes(
        snapshot.to_bytes(), expected_owner_id="owner-1"
    )

    assert restored.schema_version == 2
    assert restored.devices["shared"].provider_companion_name == "Companion guard"
    assert [
        item.device_id for item in restored.visible_devices(requester_companion_id="box", now=now)
    ] == ["shared"]
    assert [
        item.device_id for item in restored.visible_devices(requester_companion_id="guard", now=now)
    ] == ["private", "shared"]


def test_snapshot_fails_closed_after_hub_or_device_lease_expires():
    now = datetime.now(UTC)
    entry = _entry("guard", companion_id="guard")
    expired_hub = OwnerDeviceBlackboardSnapshot(
        owner_id="owner-1",
        epoch="epoch-1",
        revision=1,
        ready=True,
        hub_lease_expires_at=now - timedelta(seconds=1),
        updated_at=now,
        devices={"guard": entry},
    )
    expired_device = OwnerDeviceBlackboardSnapshot(
        owner_id="owner-1",
        epoch="epoch-1",
        revision=1,
        ready=True,
        hub_lease_expires_at=now + timedelta(seconds=30),
        updated_at=now,
        devices={
            "guard": entry.model_copy(update={"lease_expires_at": now - timedelta(seconds=1)})
        },
    )

    assert expired_hub.visible_devices(requester_companion_id="guard", now=now) == []
    assert expired_device.visible_devices(requester_companion_id="guard", now=now) == []


def test_snapshot_rejects_cross_owner_read():
    now = datetime.now(UTC)
    snapshot = OwnerDeviceBlackboardSnapshot(
        owner_id="owner-1",
        epoch="epoch-1",
        revision=1,
        ready=True,
        hub_lease_expires_at=now + timedelta(seconds=30),
        updated_at=now,
    )
    with pytest.raises(ValueError, match="owner mismatch"):
        OwnerDeviceBlackboardSnapshot.from_bytes(snapshot.to_bytes(), expected_owner_id="owner-2")
