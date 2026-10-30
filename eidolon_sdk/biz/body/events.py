"""Device-originated state events on ``eidolon.event``.

A command carries an intent and comes back as an acknowledgement. An event is
the other direction and a different thing: the device saying something changed
on its own — a knob turned, a light adjusted locally — with nobody having asked.
Keeping them apart is why events do not travel on ``eidolon.control``; that
topic's reader accepts only ``ack`` and ``result``, and widening it to also mean
"unsolicited notification" would make every receipt parser re-decide what it is
looking at.

The envelope below is the shape the firmware already builds in
``device_event_builder.cc``: a top-level ``schema_v``/``kind``, a nested
``source`` object naming the device and component, the timestamps, and a
``payload`` object. Field names are the wire names, not tidied-up Python ones, so
a reader can compare this against a captured packet directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from eidolon_sdk.biz.contracts import EVENT_TOPIC

#: A device reporting that one of its settable values changed locally.
#: Named after the value, not the cause, so a physical knob and a firmware-side
#: policy produce the same event and a reader needs no new case.
BODY_STATE_CHANGED_TYPE = "body.state.changed"

#: The envelope version this reader understands. The firmware stamps it so a
#: receiver refuses a shape it was not written for instead of misreading one.
DEVICE_EVENT_SCHEMA_VERSION = 1

#: How large a device event may be before it is refused. Bigger than any event
#: this contract defines, small enough that a malformed or hostile packet cannot
#: make a reader hold an unbounded buffer.
MAX_DEVICE_EVENT_BYTES = 4096

#: Keys an event may report. Each is the same name a capability uses for the
#: same value, so ``volume`` here and ``volume.get``'s result field are one
#: vocabulary rather than two.
BODY_STATE_KEYS = frozenset({"volume", "brightness"})

_REQUIRED_STRINGS = ("event_id", "flow_id", "type")


@dataclass(frozen=True, slots=True)
class DeviceStateChangedEvent:
    """One locally-observed change of a settable device value."""

    event_id: str
    device_id: str
    key: str
    value: int
    occurred_at_ms: int


def read_device_event(
    packet: Any, *, device: str, max_bytes: int = MAX_DEVICE_EVENT_BYTES
) -> dict[str, Any] | None:
    """Return the event body if this packet is one this device may send.

    ``None`` means "not an event I can use", never "something went wrong": the
    same rule ``read_control_receipt`` follows one topic over. Every reason to
    reject — wrong topic, wrong sender, oversized, malformed, unknown type —
    collapses to ``None`` because a reader has no useful action for the
    difference and must not log a stream of them.
    """

    if getattr(packet, "topic", None) != EVENT_TOPIC:
        return None
    sender = getattr(getattr(packet, "participant", None), "identity", None)
    if sender != device:
        return None
    try:
        data = bytes(packet.data)
        if len(data) > max_bytes:
            return None
        body = json.loads(data)
    except (AttributeError, TypeError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict) or body.get("kind") != "event":
        return None
    if type(body.get("schema_v")) is not int or body["schema_v"] != DEVICE_EVENT_SCHEMA_VERSION:
        return None
    if any(not isinstance(body.get(key), str) or not body[key] for key in _REQUIRED_STRINGS):
        return None
    source = body.get("source")
    if not isinstance(source, dict) or source.get("device_id") != device:
        return None
    if body["type"] != BODY_STATE_CHANGED_TYPE:
        return None
    return body


def device_state_changed_from_event(body: dict[str, Any]) -> DeviceStateChangedEvent | None:
    """Read a ``body.state.changed`` payload, or ``None`` if it says nothing usable.

    The payload carries the value under ``key``/``value`` rather than as a bare
    field so one event type covers every settable value without the schema
    growing a property per knob.
    """

    payload = body.get("payload")
    if not isinstance(payload, dict):
        return None
    key = payload.get("key")
    value = payload.get("value")
    if key not in BODY_STATE_KEYS:
        return None
    if type(value) is not int or not 0 <= value <= 100:
        return None
    occurred_at_ms = body.get("occurred_at_ms")
    if type(occurred_at_ms) is not int or occurred_at_ms < 0:
        return None
    return DeviceStateChangedEvent(
        event_id=body["event_id"],
        device_id=body["source"]["device_id"],
        key=key,
        value=value,
        occurred_at_ms=occurred_at_ms,
    )
