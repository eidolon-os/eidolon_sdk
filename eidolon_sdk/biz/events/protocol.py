"""Strict contracts for short-lived owner-scoped device events.

The Hub authenticates the publisher, rewrites ``source``, derives the owner
scope from the device binding, and broadcasts the normalized event. Event
types describe facts; they never name or select a receiving device.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

EVENT_SCHEMA_VERSION = 1
EVENT_DEFAULT_TTL_MS = 3_000
EVENT_MAX_CLOCK_SKEW_MS = 1_000
EVENT_MAX_BYTES = 2_048

AMBIENT_PRESENCE_CHANGED_TYPE = "ambient.presence.changed"
IDENTITY_OWNER_PRESENCE_CONFIRMED_TYPE = "identity.owner_presence.confirmed"

_COMPONENT_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class EventSource(BaseModel):
    """Publisher identity stamped by Hub before fan-out."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    device_id: str = Field(min_length=1, max_length=128)
    component: str = Field(min_length=1, max_length=64)

    @field_validator("component")
    @classmethod
    def _component_is_namespaced_identifier(cls, value: str) -> str:
        if _COMPONENT_RE.fullmatch(value) is None:
            raise ValueError("component must be a lowercase namespaced identifier")
        return value


class AmbientPresencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    state: Literal["present", "vacant"]
    modality: Literal["mmwave"] = "mmwave"
    edge: Literal["vacant_to_present", "present_to_vacant"]

    @model_validator(mode="after")
    def _state_matches_edge(self) -> "AmbientPresencePayload":
        expected_state = {
            "vacant_to_present": "present",
            "present_to_vacant": "vacant",
        }[self.edge]
        if self.state != expected_state:
            raise ValueError("ambient presence state must match edge")
        return self


class OwnerPresenceConfirmedPayload(BaseModel):
    """Privacy-bounded evidence tying an existing Guard state to one flow."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile_revision: int = Field(ge=1)
    guard_epoch: int = Field(ge=0)
    presence_sequence: int = Field(ge=1)
    evidence: Literal["local_owner_face"] = "local_owner_face"
    raw_retention: Literal["none"] = "none"


class _DeviceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    schema_v: Literal[EVENT_SCHEMA_VERSION] = EVENT_SCHEMA_VERSION
    kind: Literal["event"] = "event"
    event_id: str = Field(min_length=1, max_length=96)
    flow_id: str = Field(min_length=1, max_length=96)
    causation_id: str = Field(default="", max_length=96)
    source: EventSource
    occurred_at_ms: int = Field(ge=0)
    expires_at_ms: int = Field(ge=1)

    @model_validator(mode="after")
    def _ttl_is_short_and_forward(self) -> "_DeviceEvent":
        ttl_ms = self.expires_at_ms - self.occurred_at_ms
        if ttl_ms <= 0:
            raise ValueError("expires_at_ms must be after occurred_at_ms")
        if ttl_ms > EVENT_DEFAULT_TTL_MS:
            raise ValueError(f"device event TTL must not exceed {EVENT_DEFAULT_TTL_MS}ms")
        return self


class AmbientPresenceChanged(_DeviceEvent):
    type: Literal[AMBIENT_PRESENCE_CHANGED_TYPE] = AMBIENT_PRESENCE_CHANGED_TYPE
    payload: AmbientPresencePayload

    @model_validator(mode="after")
    def _ambient_event_is_a_root_fact(self) -> "AmbientPresenceChanged":
        if self.causation_id:
            raise ValueError("ambient presence event must not have causation_id")
        return self


class IdentityOwnerPresenceConfirmed(_DeviceEvent):
    type: Literal[IDENTITY_OWNER_PRESENCE_CONFIRMED_TYPE] = IDENTITY_OWNER_PRESENCE_CONFIRMED_TYPE
    payload: OwnerPresenceConfirmedPayload

    @model_validator(mode="after")
    def _confirmed_event_is_derived(self) -> "IdentityOwnerPresenceConfirmed":
        if not self.causation_id:
            raise ValueError("owner presence confirmation requires causation_id")
        if self.causation_id == self.event_id:
            raise ValueError("an event cannot cause itself")
        return self


DeviceEvent = Annotated[
    AmbientPresenceChanged | IdentityOwnerPresenceConfirmed,
    Field(discriminator="type"),
]

_DEVICE_EVENT_ADAPTER = TypeAdapter(DeviceEvent)


def _json_size(payload: object) -> int:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("device event must be JSON serializable") from exc
    return len(encoded)


def parse_device_event(payload: object, *, now_ms: int | None = None) -> DeviceEvent:
    """Validate a device event, including transport size and optional expiry."""

    if not isinstance(payload, Mapping):
        raise ValueError("device event must be an object")
    if _json_size(payload) > EVENT_MAX_BYTES:
        raise ValueError(f"device event must not exceed {EVENT_MAX_BYTES} bytes")

    event = _DEVICE_EVENT_ADAPTER.validate_python(payload)
    normalized = event.model_dump(mode="json")
    if _json_size(normalized) > EVENT_MAX_BYTES:
        raise ValueError(f"normalized device event must not exceed {EVENT_MAX_BYTES} bytes")

    if now_ms is not None:
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("now_ms must be a non-negative integer")
        if event.expires_at_ms <= now_ms:
            raise ValueError("device event has expired")
        if event.occurred_at_ms > now_ms + EVENT_MAX_CLOCK_SKEW_MS:
            raise ValueError("device event occurred_at_ms is too far in the future")
    return event


def normalize_device_event(payload: object, *, now_ms: int | None = None) -> dict[str, object]:
    """Return the canonical JSON-compatible event shape."""

    return parse_device_event(payload, now_ms=now_ms).model_dump(mode="json")
