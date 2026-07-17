"""Common body-device capability definitions."""

from __future__ import annotations

from eidolon_sdk.biz.body.models import BodyCapability
from eidolon_sdk.biz.contracts import (
    CONTROL_OP_CONFIG_REFRESH,
    CONTROL_OP_PLAYBACK_STOP,
    CONTROL_OP_ROOM_JOIN,
)

BODY_OP_SOUND_PLAY = "sound.play"
BODY_OP_DISPLAY_UPDATE = "display.update"
BODY_OP_DEVICE_IDENTIFY = "device.identify"
BODY_OP_DEVICE_ROLL_CALL = "device.roll_call"
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
    BODY_OP_DEVICE_ROLL_CALL: BodyCapability(
        name=BODY_OP_DEVICE_ROLL_CALL,
        description=(
            "Respond when the user asks whether this device is present or calls it by name. "
            "The device plays its local roll-call cue."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        result_schema={
            "type": "object",
            "properties": {"played": {"type": "boolean"}},
            "required": ["played"],
            "additionalProperties": True,
        },
        risk_level="low",
        requires_ack=True,
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
