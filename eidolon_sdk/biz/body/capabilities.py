"""Common body-device capability definitions."""

from __future__ import annotations

from typing import Any

from eidolon_sdk.biz.body.models import BodyCapability
from eidolon_sdk.biz.contracts import (
    CONTROL_OP_CONFIG_REFRESH,
    CONTROL_OP_PLAYBACK_STOP,
    CONTROL_OP_ROOM_JOIN,
)

BODY_OP_SOUND_PLAY = "sound.play"
BODY_OP_DISPLAY_UPDATE = "display.update"
BODY_OP_DEVICE_IDENTIFY = "device.identify"
BODY_OP_ROOM_LEAVE = "room.leave"
BODY_OP_VOLUME_SET = "volume.set"
BODY_OP_DEVICE_REBOOT = "device.reboot"
BODY_OP_SAFETY_STOP = "safety.stop"
BODY_OP_PRESENCE_SET = "body.presence.set"


KNOWN_BODY_CAPABILITIES: dict[str, BodyCapability] = {
    BODY_OP_SOUND_PLAY: BodyCapability(
        name=BODY_OP_SOUND_PLAY,
        description="Play a short local sound cue on the device.",
        input_schema={
            "type": "object",
            "properties": {
                "sound": {"type": "string"},
                "volume": {"type": "number"},
                "duration_ms": {"type": "integer"},
            },
            "required": ["sound"],
            "additionalProperties": True,
        },
    ),
    BODY_OP_DISPLAY_UPDATE: BodyCapability(
        name=BODY_OP_DISPLAY_UPDATE,
        description="Show a short text or UI state update on the device display.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}, "ttl_ms": {"type": "integer"}},
            "required": ["text"],
            "additionalProperties": True,
        },
    ),
    BODY_OP_DEVICE_IDENTIFY: BodyCapability(
        name=BODY_OP_DEVICE_IDENTIFY,
        description="Ask a reachable device to identify itself with a local cue.",
        input_schema={
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "additionalProperties": True,
        },
    ),
    CONTROL_OP_ROOM_JOIN: BodyCapability(
        name=CONTROL_OP_ROOM_JOIN,
        description="Ask an online control-plane device to join a voice room.",
        risk_level="medium",
    ),
    BODY_OP_ROOM_LEAVE: BodyCapability(
        name=BODY_OP_ROOM_LEAVE,
        description="Ask a device to leave its current voice room.",
    ),
    CONTROL_OP_PLAYBACK_STOP: BodyCapability(
        name=CONTROL_OP_PLAYBACK_STOP,
        description="Stop the device's current playback.",
    ),
    BODY_OP_VOLUME_SET: BodyCapability(
        name=BODY_OP_VOLUME_SET,
        description="Set device playback volume.",
        input_schema={
            "type": "object",
            "properties": {"volume": {"type": "number"}},
            "required": ["volume"],
            "additionalProperties": False,
        },
    ),
    CONTROL_OP_CONFIG_REFRESH: BodyCapability(
        name=CONTROL_OP_CONFIG_REFRESH,
        description="Ask the device to refresh its runtime configuration.",
    ),
    BODY_OP_DEVICE_REBOOT: BodyCapability(
        name=BODY_OP_DEVICE_REBOOT,
        description="Reboot the device.",
        risk_level="high",
        requires_confirmation=True,
    ),
    BODY_OP_SAFETY_STOP: BodyCapability(
        name=BODY_OP_SAFETY_STOP,
        description="Immediately stop motion or other safety-critical activity.",
        risk_level="critical",
    ),
    BODY_OP_PRESENCE_SET: BodyCapability(
        name=BODY_OP_PRESENCE_SET,
        description="Set a low-risk local presence state on a body device.",
        input_schema={
            "type": "object",
            "properties": {
                "state": {"type": "string"},
                "guard_epoch": {"type": "integer"},
                "correlation_id": {"type": "string"},
                "action_id": {"type": "string"},
            },
            "required": ["state", "guard_epoch", "correlation_id", "action_id"],
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "state": {"type": "string"},
                "applied": {"type": "boolean"},
            },
            "required": ["action_id", "applied"],
            "additionalProperties": True,
        },
        risk_level="low",
        requires_ack=True,
    ),
}


def capability_from_json(value: Any) -> BodyCapability | None:
    if isinstance(value, str):
        return KNOWN_BODY_CAPABILITIES.get(value) or BodyCapability(name=value)
    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or value.get("op") or "").strip()
    if not name:
        return None
    base = KNOWN_BODY_CAPABILITIES.get(name)
    return BodyCapability(
        name=name,
        description=str(value.get("description") or (base.description if base else "")),
        input_schema=dict(value.get("input_schema") or value.get("schema") or (base.input_schema if base else {})),
        result_schema=dict(value.get("result_schema") or (base.result_schema if base else {})),
        side_effect=bool(value.get("side_effect", base.side_effect if base else True)),
        requires_online=bool(value.get("requires_online", base.requires_online if base else True)),
        requires_ack=bool(value.get("requires_ack", base.requires_ack if base else True)),
        risk_level=value.get("risk_level") or (base.risk_level if base else "low"),
        requires_confirmation=bool(
            value.get(
                "requires_confirmation",
                base.requires_confirmation if base else False,
            )
        ),
    )


def capabilities_from_json(value: Any, *, device_kind: str = "unknown") -> tuple[BodyCapability, ...]:
    raw_items: list[Any]
    if isinstance(value, dict):
        if isinstance(value.get("capabilities"), list):
            raw_items = list(value["capabilities"])
        elif isinstance(value.get("ops"), list):
            raw_items = list(value["ops"])
        elif isinstance(value.get("body"), list):
            raw_items = list(value["body"])
        else:
            raw_items = [key for key, enabled in value.items() if enabled is True]
    elif isinstance(value, list):
        raw_items = list(value)
    else:
        raw_items = []

    capabilities = [item for raw in raw_items if (item := capability_from_json(raw)) is not None]
    if capabilities:
        return tuple(_dedupe_capabilities(capabilities))
    if _is_default_body_device_kind(device_kind):
        return tuple(
            KNOWN_BODY_CAPABILITIES[name]
            for name in (
                BODY_OP_SOUND_PLAY,
                BODY_OP_DISPLAY_UPDATE,
                BODY_OP_DEVICE_IDENTIFY,
                CONTROL_OP_ROOM_JOIN,
                BODY_OP_ROOM_LEAVE,
                CONTROL_OP_PLAYBACK_STOP,
                BODY_OP_VOLUME_SET,
            )
        )
    return ()


def _is_default_body_device_kind(device_kind: str) -> bool:
    normalized = device_kind.strip().lower()
    return any(token in normalized for token in ("esp", "box", "speaker", "screen", "display"))


def _dedupe_capabilities(items: list[BodyCapability]) -> list[BodyCapability]:
    seen: set[str] = set()
    out: list[BodyCapability] = []
    for item in items:
        if item.name in seen:
            continue
        seen.add(item.name)
        out.append(item)
    return out
