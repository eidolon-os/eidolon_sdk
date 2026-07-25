from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.contracts import EVENT_TOPIC
from eidolon_sdk.biz.events import (
    AMBIENT_PRESENCE_CHANGED_TYPE,
    EVENT_DEFAULT_TTL_MS,
    EVENT_MAX_CLOCK_SKEW_MS,
    EVENT_MAX_BYTES,
    IDENTITY_OWNER_PRESENCE_CONFIRMED_TYPE,
    AmbientPresenceChanged,
    IdentityOwnerPresenceConfirmed,
    normalize_device_event,
    parse_device_event,
)


def _ambient(**patch: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_v": 1,
        "kind": "event",
        "event_id": "evt-radar-1",
        "flow_id": "flow-radar-1",
        "causation_id": "",
        "type": AMBIENT_PRESENCE_CHANGED_TYPE,
        "source": {"device_id": "box3-01", "component": "radar"},
        "occurred_at_ms": 10_000,
        "expires_at_ms": 10_000 + EVENT_DEFAULT_TTL_MS,
        "payload": {
            "state": "present",
            "modality": "mmwave",
            "edge": "vacant_to_present",
        },
    }
    payload.update(patch)
    return payload


def _confirmed(**patch: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_v": 1,
        "kind": "event",
        "event_id": "evt-owner-1",
        "flow_id": "flow-radar-1",
        "causation_id": "evt-radar-1",
        "type": IDENTITY_OWNER_PRESENCE_CONFIRMED_TYPE,
        "source": {"device_id": "atk-01", "component": "guard.owner_face"},
        "occurred_at_ms": 10_500,
        "expires_at_ms": 13_000,
        "payload": {
            "profile_revision": 7,
            "guard_epoch": 12,
            "presence_sequence": 33,
            "evidence": "local_owner_face",
            "raw_retention": "none",
        },
    }
    payload.update(patch)
    return payload


def test_topic_and_event_types_are_stable_contracts() -> None:
    assert EVENT_TOPIC == "eidolon.event"
    assert AMBIENT_PRESENCE_CHANGED_TYPE == "ambient.presence.changed"
    assert IDENTITY_OWNER_PRESENCE_CONFIRMED_TYPE == "identity.owner_presence.confirmed"


def test_parse_ambient_presence_event() -> None:
    event = parse_device_event(_ambient(), now_ms=12_999)

    assert isinstance(event, AmbientPresenceChanged)
    assert event.payload.state == "present"
    assert event.flow_id == "flow-radar-1"


def test_parse_owner_confirmation_event() -> None:
    event = parse_device_event(_confirmed(), now_ms=12_999)

    assert isinstance(event, IdentityOwnerPresenceConfirmed)
    assert event.causation_id == "evt-radar-1"
    assert event.payload.raw_retention == "none"


def test_normalization_keeps_complete_explicit_wire_shape() -> None:
    normalized = normalize_device_event(_ambient())

    assert normalized == _ambient()


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"schema_v": 2}, "Input should be 1"),
        ({"kind": "command"}, "Input should be 'event'"),
        ({"type": "box3.ask_atk"}, "union_tag_invalid"),
        ({"expires_at_ms": 10_000}, "must be after"),
        ({"expires_at_ms": 13_001}, "must not exceed"),
    ],
)
def test_rejects_invalid_envelope_contract(patch: dict[str, object], message: str) -> None:
    with pytest.raises((ValidationError, ValueError), match=message):
        parse_device_event(_ambient(**patch))


def test_rejects_expired_event() -> None:
    with pytest.raises(ValueError, match="expired"):
        parse_device_event(_ambient(), now_ms=13_000)


def test_rejects_event_timestamp_too_far_in_the_future() -> None:
    now_ms = 10_000
    occurred_at_ms = now_ms + EVENT_MAX_CLOCK_SKEW_MS + 1

    with pytest.raises(ValueError, match="occurred_at_ms.*future"):
        parse_device_event(
            _ambient(
                occurred_at_ms=occurred_at_ms,
                expires_at_ms=occurred_at_ms + EVENT_DEFAULT_TTL_MS,
            ),
            now_ms=now_ms,
        )


def test_ambient_presence_is_a_root_event() -> None:
    with pytest.raises(ValidationError, match="must not have causation_id"):
        parse_device_event(_ambient(causation_id="evt-upstream"))


def test_rejects_unknown_fields_at_every_level() -> None:
    top = _ambient(debug_target="atk-01")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        parse_device_event(top)

    source = _ambient()
    source["source"] = {**source["source"], "owner_id": "owner-1"}  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        parse_device_event(source)

    nested = _confirmed()
    nested["payload"] = {**nested["payload"], "image_url": "secret"}  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        parse_device_event(nested)


def test_rejects_mismatched_presence_state_and_edge() -> None:
    event = _ambient()
    payload = copy.deepcopy(event["payload"])
    assert isinstance(payload, dict)
    payload["state"] = "vacant"
    event["payload"] = payload

    with pytest.raises(ValidationError, match="state must match edge"):
        parse_device_event(event)


@pytest.mark.parametrize("causation_id", ["", "evt-owner-1"])
def test_owner_confirmation_requires_real_causation(causation_id: str) -> None:
    with pytest.raises(ValidationError, match="causation|cause itself"):
        parse_device_event(_confirmed(causation_id=causation_id))


def test_rejects_non_strict_scalar_coercion() -> None:
    with pytest.raises(ValidationError):
        parse_device_event(_ambient(occurred_at_ms="10000"))


def test_rejects_oversized_event_before_schema_validation() -> None:
    event = _ambient(padding="x" * EVENT_MAX_BYTES)

    with pytest.raises(ValueError, match=f"{EVENT_MAX_BYTES} bytes"):
        parse_device_event(event)


@pytest.mark.parametrize("now_ms", [-1, 1.5, True])
def test_now_ms_is_strict_non_negative_integer(now_ms: object) -> None:
    with pytest.raises(ValueError, match="now_ms"):
        parse_device_event(_ambient(), now_ms=now_ms)  # type: ignore[arg-type]
