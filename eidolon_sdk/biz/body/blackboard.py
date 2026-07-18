"""Owner-isolated runtime device blackboard wire models.

The blackboard is a current-state projection, not durable device inventory.
Each owner has exactly one JetStream KV value containing the complete device
snapshot that may be exposed to that owner's companions.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eidolon_sdk.biz.body.manifest import CapabilityDeclaration, CapabilityManifest

DEVICE_BLACKBOARD_BUCKET = "EIDOLON_RUNTIME_DEVICES"
DEVICE_BLACKBOARD_SCHEMA_VERSION = 2

RuntimeDeviceStatus = Literal["registered_waiting_transport", "online"]
CapabilityVisibility = Literal["owner", "bound_companion"]


def owner_device_blackboard_key(owner_id: str) -> str:
    """Return an opaque, NATS-safe key for one owner's current snapshot."""
    normalized = owner_id.strip()
    if not normalized:
        raise ValueError("owner_id is required")
    token = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"owner.{token}.current"


def capability_manifest_revision(manifest: CapabilityManifest) -> str:
    payload = manifest.model_dump(mode="json")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


class RuntimeDeviceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    device_id: str = Field(min_length=1, max_length=128)
    registration_id: str = Field(min_length=1, max_length=128)
    provider_companion_id: str | None = Field(default=None, max_length=128)
    provider_companion_name: str = Field(default="", max_length=128)
    name: str = Field(default="", max_length=128)
    aliases: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    visibility: CapabilityVisibility = "owner"
    capabilities: tuple[CapabilityDeclaration, ...] = Field(default_factory=tuple)
    manifest_revision: str = Field(min_length=1, max_length=128)
    status: RuntimeDeviceStatus = "registered_waiting_transport"
    registered_at: datetime
    lease_expires_at: datetime
    last_seen_at: datetime | None = None
    room_name: str = Field(default="", max_length=256)
    participant_sid: str = Field(default="", max_length=128)
    presence_revision: str = Field(default="", max_length=128)

    def capability(self, name: str, version: int | None = None) -> CapabilityDeclaration | None:
        """Find a declared capability, optionally pinned to an exact version.

        Name-only lookup is for discovery and policy checks. Command execution
        must pass ``version`` so dispatch cannot silently cross contract versions.
        """
        for capability in self.capabilities:
            if capability.name == name and (version is None or capability.version == version):
                return capability
        return None

    def is_online(self, *, now: datetime | None = None) -> bool:
        effective_now = now or datetime.now(UTC)
        return self.status == "online" and self.lease_expires_at > effective_now


class OwnerDeviceBlackboardSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = DEVICE_BLACKBOARD_SCHEMA_VERSION
    owner_id: str = Field(min_length=1, max_length=64)
    epoch: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    ready: bool = False
    hub_lease_expires_at: datetime
    updated_at: datetime
    devices: dict[str, RuntimeDeviceEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _device_keys_match_entries(self) -> "OwnerDeviceBlackboardSnapshot":
        for device_id, entry in self.devices.items():
            if device_id != entry.device_id:
                raise ValueError("device map key must match entry.device_id")
        return self

    def is_available(self, *, now: datetime | None = None) -> bool:
        effective_now = now or datetime.now(UTC)
        return self.ready and self.hub_lease_expires_at > effective_now

    def visible_devices(
        self,
        *,
        requester_companion_id: str,
        now: datetime | None = None,
    ) -> list[RuntimeDeviceEntry]:
        effective_now = now or datetime.now(UTC)
        if not self.is_available(now=effective_now):
            return []
        visible = []
        for entry in self.devices.values():
            if not entry.is_online(now=effective_now) or not entry.provider_companion_id:
                continue
            if (
                entry.visibility == "bound_companion"
                and entry.provider_companion_id != requester_companion_id
            ):
                continue
            visible.append(entry)
        return sorted(visible, key=lambda item: item.device_id)

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_bytes(
        cls,
        value: bytes,
        *,
        expected_owner_id: str | None = None,
    ) -> "OwnerDeviceBlackboardSnapshot":
        snapshot = cls.model_validate_json(value)
        if expected_owner_id is not None and snapshot.owner_id != expected_owner_id:
            raise ValueError("device blackboard owner mismatch")
        return snapshot


__all__ = [
    "CapabilityVisibility",
    "DEVICE_BLACKBOARD_BUCKET",
    "DEVICE_BLACKBOARD_SCHEMA_VERSION",
    "OwnerDeviceBlackboardSnapshot",
    "RuntimeDeviceEntry",
    "RuntimeDeviceStatus",
    "capability_manifest_revision",
    "owner_device_blackboard_key",
]
