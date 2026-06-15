"""Device control command/ack wire protocol."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

CONTROL_TOPIC = "eidolon.control"
CONTROL_PROTOCOL_VERSION = 1

CommandQoS = Literal["fire_and_forget", "ack", "result"]
CommandPriority = Literal["low", "normal", "high", "urgent"]

_ACK_STATUSES = {
    "accepted",
    "running",
    "succeeded",
    "failed",
    "rejected",
    "unsupported",
    "expired",
}


def unix_ms(dt: datetime | None = None) -> int:
    value = dt or datetime.now(UTC)
    return int(value.timestamp() * 1000)


def infer_op(payload: dict[str, Any], explicit_op: str | None = None) -> str:
    if explicit_op:
        return explicit_op
    for key in ("op", "type", "command"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return "device.command"


def build_command_envelope(
    *,
    command_id: str,
    device_id: str,
    payload: dict[str, Any],
    op: str | None = None,
    ttl_ms: int = 30_000,
    qos: CommandQoS = "ack",
    priority: CommandPriority = "normal",
    src_type: str = "hub",
    src_id: str = "eidolon_hub",
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a versioned device command envelope.

    The trailing compatibility fields are intentionally part of the SDK
    contract while older ESP32 firmware and admin traces still read them.
    """

    resolved_op = infer_op(payload, op)
    body: dict[str, Any] = {
        "v": CONTROL_PROTOCOL_VERSION,
        "kind": "cmd",
        "id": command_id,
        "op": resolved_op,
        "ts": unix_ms(created_at),
        "ttl_ms": ttl_ms,
        "qos": qos,
        "priority": priority,
        "src": {"type": src_type, "id": src_id},
        "dst": {"type": "device", "id": device_id},
        "payload": payload,
        "caps": ["ack.v1", "result.v1"],
    }
    body["type"] = resolved_op
    body["command_id"] = command_id
    body["device_id"] = device_id
    return body


def normalize_ack_status(status: str) -> str:
    value = status.lower()
    if value in _ACK_STATUSES:
        return value
    return "failed"


def command_status_from_ack(status: str) -> str:
    value = normalize_ack_status(status)
    if value in {"accepted", "running"}:
        return value
    if value == "unsupported":
        return "failed"
    return value
