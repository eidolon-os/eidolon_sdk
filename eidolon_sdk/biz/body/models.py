"""Shared body-device protocol models.

These dataclasses describe the semantic layer above the low-level
``eidolon.control`` command envelope. Agent, admin, hub, and device clients can
share these names without sharing transport implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from eidolon_sdk.biz.control import CommandPriority, CommandQoS

BodyDeviceStatus = Literal["online_control", "in_voice", "offline", "unknown"]
BodyCommandStatus = Literal[
    "accepted",
    "sent",
    "done",
    "running",
    "failed",
    "timeout",
    "offline",
    "unsupported",
    "queued",
    "rejected",
]
BodyRiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class BodyCapability:
    name: str
    version: int = 1
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    result_schema: dict[str, Any] = field(default_factory=dict)
    side_effect: bool = True
    requires_online: bool = True
    requires_ack: bool = True
    risk_level: BodyRiskLevel = "low"
    requires_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class BodyDevice:
    device_id: str
    name: str = ""
    aliases: tuple[str, ...] = ()
    provider_companion_id: str = ""
    kind: str = "unknown"
    status: BodyDeviceStatus = "unknown"
    is_current_device: bool = False
    last_seen: datetime | None = None
    control_room_name: str = ""
    capabilities: tuple[BodyCapability, ...] = ()

    def supports(self, op: str) -> bool:
        return any(capability.name == op for capability in self.capabilities)

    def capability(self, op: str) -> BodyCapability | None:
        for capability in self.capabilities:
            if capability.name == op:
                return capability
        return None


@dataclass(frozen=True, slots=True)
class BodyCommand:
    target_device_id: str
    op: str
    payload: dict[str, Any] = field(default_factory=dict)
    qos: CommandQoS = "ack"
    ttl_ms: int = 30_000
    priority: CommandPriority = "normal"
    idempotency_key: str | None = None
    source: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BodyCommandResult:
    command_id: str
    device_id: str
    op: str
    status: BodyCommandStatus
    message: str = ""
    ack: dict[str, Any] | None = None
    result: Any = None
    error: str = ""
    updated_at: datetime | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"accepted", "sent", "done", "running", "queued"}


def device_to_dict(device: BodyDevice) -> dict[str, Any]:
    return {
        "device_id": device.device_id,
        "name": device.name,
        "aliases": list(device.aliases),
        "provider_companion_id": device.provider_companion_id,
        "kind": device.kind,
        "status": device.status,
        "is_current_device": device.is_current_device,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        "control_room_name": device.control_room_name,
        "capabilities": [capability_to_dict(item) for item in device.capabilities],
    }


def capability_to_dict(capability: BodyCapability) -> dict[str, Any]:
    return {
        "name": capability.name,
        "version": capability.version,
        "description": capability.description,
        "input_schema": capability.input_schema,
        "result_schema": capability.result_schema,
        "side_effect": capability.side_effect,
        "requires_online": capability.requires_online,
        "requires_ack": capability.requires_ack,
        "risk_level": capability.risk_level,
        "requires_confirmation": capability.requires_confirmation,
    }


def command_result_to_dict(result: BodyCommandResult) -> dict[str, Any]:
    return {
        "command_id": result.command_id,
        "device_id": result.device_id,
        "op": result.op,
        "status": result.status,
        "message": result.message,
        "ack": result.ack,
        "result": result.result,
        "error": result.error,
        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
        "ok": result.ok,
    }
