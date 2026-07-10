"""Owner data model contracts shared by Eidolon projects."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OwnerRef(BaseModel):
    owner_id: str = Field(..., min_length=1, max_length=64)
    display_name: str = ""
    kind: str = "person"
    status: str = "active"


class CompanionRef(BaseModel):
    companion_id: str = Field(..., min_length=1, max_length=64)
    owner_id: str = Field(..., min_length=1, max_length=64)
    display_name: str = ""
    kind: str = "companion"
    status: str = "active"
    current_genome_id: str | None = None
    default_memory_realm_id: str | None = None


class DeviceRegistryRecord(BaseModel):
    """Physical/client device discovery record.

    Device ids are hardware/client generated and may be MAC addresses, so they
    intentionally do not use the stricter owner id rules.
    """

    device_id: str = Field(..., min_length=1, max_length=128)
    name: str = ""
    kind: str = "unknown"
    enabled: bool = True
    psk_hash: str | None = None
    paired: bool = False
    approved: bool = False
    approved_at: str | None = None
    created_at: str = ""
    last_seen: str = ""
    metadata: dict = Field(default_factory=dict)
    # Device-declared capability manifest (capability_to_dict shape), submitted at
    # registration. Empty means "not declared" — the persistence layer then
    # preserves any operator/onboarding-authored capabilities rather than clearing
    # them. Non-empty replaces them (the device is source of truth for its own body).
    capabilities: list[dict] = Field(default_factory=list)


class DeviceBindingRecord(BaseModel):
    """Owner-scoped pointer from one device to one companion."""

    device_id: str = Field(..., min_length=1, max_length=128)
    owner_id: str = Field(..., min_length=1, max_length=64)
    companion_id: str = Field(..., min_length=1, max_length=64)
    memory_realm_id: str = Field(..., min_length=1, max_length=64)
    genome_id: str = Field(..., min_length=1, max_length=64)
    bound_at: str
    interaction_mode: str | None = None
