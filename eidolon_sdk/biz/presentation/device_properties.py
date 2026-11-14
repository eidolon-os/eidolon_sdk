"""Observable device properties: what a device reports about its own values.

Two ways a reader learns a value, both answered by the device:

- ``property.changed`` on ``eidolon.event``, in the envelope the firmware already
  builds for every device event. Sent whenever the value changes for any reason,
  so a reader is told rather than asking again.
- ``eidolon.properties.read.v1`` over LiveKit RPC, which returns the current
  value of each observable property. A reader that joined after the last change,
  or restarted, asks once instead of waiting for the next one.

Which properties exist and what values they admit are the Host's installed
declarations (``eidolon_sdk.biz.capabilities.installed_properties``), never the
device's word: a value is read only for a property the device declared exactly
as installed, and only when that schema admits it.

A command and an event stay on separate topics. ``eidolon.control`` carries
intents and their receipts; widening it to also mean "something changed on its
own" would make every receipt parser re-decide what it is looking at.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import Field

from eidolon_sdk.biz.capabilities import check_property_value
from eidolon_sdk.biz.contracts import EVENT_TOPIC

from . import Contract

PROPERTY_CHANGED = "property.changed"
PROPERTIES_READ = "eidolon.properties.read.v1"

#: The firmware stamps every device event with this; a reader refuses a shape it
#: was not written for rather than misreading it.
DEVICE_EVENT_SCHEMA_VERSION = 1
#: The firmware's own bound on one event (``DeviceEventBus::kMaxEventBytes``).
MAX_DEVICE_EVENT_BYTES = 2048


class PropertyValues(Contract):
    """The answer to ``eidolon.properties.read.v1``: every observable value, now."""

    values: dict[str, Any] = Field(default_factory=dict, max_length=64)


@dataclass(frozen=True, slots=True)
class PropertyChange:
    device_id: str
    name: str
    value: Any
    event_id: str
    occurred_at_ms: int


def read_property_change(
    packet: Any, *, device: str, declared: Mapping[str, dict]
) -> PropertyChange | None:
    """A ``property.changed`` this device may send about a property it declared.

    ``None`` means "not one I can use", never "something went wrong": wrong
    topic, wrong sender, oversized, malformed, another event type, an undeclared
    property or a value its schema refuses all collapse to it, because a reader
    has no different action for any of them and must not log a stream of them.
    """

    if getattr(packet, "topic", None) != EVENT_TOPIC:
        return None
    if getattr(getattr(packet, "participant", None), "identity", None) != device:
        return None
    try:
        data = bytes(packet.data)
        if len(data) > MAX_DEVICE_EVENT_BYTES:
            return None
        body = json.loads(data)
    except (AttributeError, TypeError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict) or body.get("kind") != "event":
        return None
    if type(body.get("schema_v")) is not int or body["schema_v"] != DEVICE_EVENT_SCHEMA_VERSION:
        return None
    if body.get("type") != PROPERTY_CHANGED:
        return None
    event_id = body.get("event_id")
    source = body.get("source")
    occurred_at_ms = body.get("occurred_at_ms")
    payload = body.get("payload")
    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(source, dict)
        or source.get("device_id") != device
        or type(occurred_at_ms) is not int
        or occurred_at_ms < 0
        or not isinstance(payload, dict)
    ):
        return None
    return _change(device, payload.get("name"), payload.get("value"), declared,
                   event_id=event_id, occurred_at_ms=occurred_at_ms)


def read_property_values(
    answer: PropertyValues, *, declared: Mapping[str, dict]
) -> dict[str, Any]:
    """The values in a read answer that a declared schema admits; the rest dropped."""

    accepted: dict[str, Any] = {}
    for name, value in answer.values.items():
        schema = declared.get(name)
        if schema is None:
            continue
        try:
            check_property_value(schema, value)
        except ValueError:
            continue
        accepted[name] = value
    return accepted


def _change(device, name, value, declared, *, event_id, occurred_at_ms):
    schema = declared.get(name) if isinstance(name, str) else None
    if schema is None:
        return None
    try:
        check_property_value(schema, value)
    except ValueError:
        return None
    return PropertyChange(
        device_id=device, name=name, value=value, event_id=event_id,
        occurred_at_ms=occurred_at_ms,
    )
