"""The ``body.state.changed`` event a device sends on its own initiative.

Different from a command receipt in one way that decides everything else: nobody
asked. A reader must therefore distrust it more, not less — it arrives on a
topic the device can write at will, and the only thing making it trustworthy is
that the sender identity matches the device the reader was already watching.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from eidolon_sdk.biz.body import (
    BODY_STATE_CHANGED_TYPE,
    MAX_DEVICE_EVENT_BYTES,
    device_state_changed_from_event,
    read_device_event,
)
from eidolon_sdk.biz.contracts import CONTROL_TOPIC, EVENT_TOPIC

_DEVICE = "device-instance-abc"


def _body(**overrides: object) -> dict:
    body: dict = {
        "schema_v": 1,
        "kind": "event",
        "event_id": "evt-state-1",
        "flow_id": "flow-1",
        "causation_id": "",
        "type": BODY_STATE_CHANGED_TYPE,
        "source": {"device_id": _DEVICE, "component": "actuator"},
        "occurred_at_ms": 1_700_000_000_000,
        "expires_at_ms": 1_700_000_060_000,
        "payload": {"key": "volume", "value": 42},
    }
    body.update(overrides)
    return body


def _packet(body: object, *, topic: str = EVENT_TOPIC, sender: str | None = _DEVICE):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    return SimpleNamespace(
        topic=topic,
        participant=SimpleNamespace(identity=sender) if sender is not None else None,
        data=data,
    )


def test_a_device_state_event_is_recognised() -> None:
    body = read_device_event(_packet(_body()), device=_DEVICE)

    assert body is not None
    assert body["type"] == BODY_STATE_CHANGED_TYPE


def test_the_control_topic_is_not_an_event_topic() -> None:
    assert read_device_event(_packet(_body(), topic=CONTROL_TOPIC), device=_DEVICE) is None


@pytest.mark.parametrize("sender", ["some-other-device", None])
def test_only_the_watched_device_may_report_its_own_state(sender: str | None) -> None:
    assert read_device_event(_packet(_body(), sender=sender), device=_DEVICE) is None


def test_a_body_naming_a_different_device_is_refused() -> None:
    packet = _packet(_body(source={"device_id": "device-instance-other", "component": "actuator"}))

    assert read_device_event(packet, device=_DEVICE) is None


@pytest.mark.parametrize("field", ["event_id", "flow_id", "type"])
def test_an_envelope_missing_its_identity_is_refused(field: str) -> None:
    body = _body()
    del body[field]

    assert read_device_event(_packet(body), device=_DEVICE) is None


@pytest.mark.parametrize("source", [None, "actuator", {}, {"component": "actuator"}])
def test_an_unreadable_source_is_refused(source: object) -> None:
    assert read_device_event(_packet(_body(source=source)), device=_DEVICE) is None


@pytest.mark.parametrize("kind", ["ack", "result", "cmd", ""])
def test_only_a_packet_declaring_itself_an_event_is_read(kind: str) -> None:
    assert read_device_event(_packet(_body(kind=kind)), device=_DEVICE) is None


@pytest.mark.parametrize("schema", [0, 2, "1", None, True])
def test_an_envelope_version_this_reader_does_not_know_is_refused(schema: object) -> None:
    assert read_device_event(_packet(_body(schema_v=schema)), device=_DEVICE) is None


@pytest.mark.parametrize("raw", [b"{bad", b"null", b"[]", b"", b'{"v":true}'])
def test_a_malformed_packet_is_refused_rather_than_raising(raw: bytes) -> None:
    assert read_device_event(_packet(raw), device=_DEVICE) is None


def test_an_oversized_packet_is_refused() -> None:
    body = _body(padding="x" * MAX_DEVICE_EVENT_BYTES)

    assert read_device_event(_packet(body), device=_DEVICE) is None


def test_an_unknown_event_type_is_not_read_as_this_one() -> None:
    assert read_device_event(_packet(_body(type="body.other.thing")), device=_DEVICE) is None


@pytest.mark.parametrize(
    ("key", "value"),
    [("volume", 42), ("brightness", 90), ("volume", 0), ("brightness", 100)],
)
def test_a_known_key_with_its_bounded_value_is_read(key: str, value: int) -> None:
    body = read_device_event(_packet(_body(payload={"key": key, "value": value})), device=_DEVICE)

    event = device_state_changed_from_event(body)

    assert event is not None
    assert (event.key, event.value) == (key, value)
    assert event.device_id == _DEVICE


@pytest.mark.parametrize("payload", [{"key": "unknown", "value": 10}, {"key": "volume"}])
def test_an_unusable_payload_yields_no_event(payload: dict) -> None:
    body = read_device_event(_packet(_body(payload=payload)), device=_DEVICE)

    assert device_state_changed_from_event(body) is None


@pytest.mark.parametrize("value", [-1, 101, "42", 42.5, True, None])
def test_a_value_outside_the_bounded_integer_is_refused(value: object) -> None:
    body = read_device_event(
        _packet(_body(payload={"key": "volume", "value": value})), device=_DEVICE
    )

    assert device_state_changed_from_event(body) is None


def test_a_payload_that_is_not_an_object_yields_no_event() -> None:
    body = read_device_event(_packet(_body(payload="volume=42")), device=_DEVICE)

    assert device_state_changed_from_event(body) is None
