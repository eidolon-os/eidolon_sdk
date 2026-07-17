from __future__ import annotations

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.sense import (
    SENSE_SCHEMA_VERSION,
    SenseAttention,
    SenseEvent,
    SenseFatigue,
    SenseSession,
    parse_sense_message,
)


def _envelope() -> dict:
    return {
        "schema_v": 1,
        "owner_id": "owner-1",
        "device_id": "atk-1",
        "correlation_id": "sn-boot1-r5-e3",
        "epoch": 3,
        "ts_ms": 1_700_000_000_000,
    }


def _attention(**over) -> dict:
    return {**_envelope(), "type": "sense.attention", "state": "focused", **over}


def _session(**over) -> dict:
    return {**_envelope(), "type": "sense.session", "state": "ended", "duration_ms": 280_000, **over}


def _fatigue(**over) -> dict:
    return {
        **_envelope(),
        "type": "sense.fatigue",
        "hint": "yawn",
        "confidence": 0.82,
        "model_id": "mediapipe-face-landmarker",
        "model_version": "mar-ear-v1",
        "signals": {"yawn_count": 3, "eye_closure_ms": 1200},
        **over,
    }


def _event(**over) -> dict:
    return {
        **_envelope(),
        "type": "sense.event",
        "event": "cat",
        "confidence": 0.71,
        "model_id": "mediapipe-object-detector",
        "model_version": "efficientdet-lite0-v1",
        **over,
    }


def test_each_fact_parses_via_discriminated_union() -> None:
    assert isinstance(parse_sense_message(_attention()), SenseAttention)
    assert isinstance(parse_sense_message(_session()), SenseSession)
    assert isinstance(parse_sense_message(_fatigue()), SenseFatigue)
    assert isinstance(parse_sense_message(_event()), SenseEvent)


def test_attention_is_versioned_and_privacy_bounded() -> None:
    msg = parse_sense_message(_attention(signals={"bbox_stability": 0.9}))
    assert isinstance(msg, SenseAttention)
    assert msg.schema_v == SENSE_SCHEMA_VERSION
    assert msg.raw_retention == "none"


def test_session_started_must_carry_no_metrics() -> None:
    parse_sense_message(_session(state="started", duration_ms=0, interruptions=0))
    with pytest.raises(ValidationError):
        parse_sense_message(_session(state="started", duration_ms=1000))


def test_fatigue_is_model_attributed() -> None:
    msg = parse_sense_message(_fatigue())
    assert isinstance(msg, SenseFatigue)
    assert msg.model_id and msg.model_version
    with pytest.raises(ValidationError):
        parse_sense_message(_fatigue(model_id=""))


def test_event_reports_bounded_class_only() -> None:
    assert isinstance(parse_sense_message(_event(event="package")), SenseEvent)
    with pytest.raises(ValidationError):
        parse_sense_message(_event(event="manson"))  # no identity / arbitrary labels


@pytest.mark.parametrize(
    "sensitive",
    [
        {"image": "aGVsbG8="},
        {"frame": [1, 2, 3]},
        {"embedding": [0.1, 0.2]},
        {"photo_url": "https://x/y.jpg"},
        {"unknown_field": 1},
        # owner-scoped (D1): the fact must NOT carry a companion pin
        {"companion_id": "guard-1"},
        {"guard_companion_id": "guard-1"},
    ],
)
def test_rejects_sensitive_or_unknown_fields(sensitive: dict) -> None:
    with pytest.raises(ValidationError):
        parse_sense_message(_fatigue(**sensitive))


def test_rejects_unknown_schema_version() -> None:
    with pytest.raises(ValidationError):
        parse_sense_message(_attention(schema_v=2))


@pytest.mark.parametrize(
    "patch",
    [
        {"epoch": "3"},
        {"ts_ms": "1700000000000"},
        {"confidence": "0.5"},
    ],
)
def test_rejects_string_coercion_for_numbers(patch: dict) -> None:
    with pytest.raises(ValidationError):
        parse_sense_message(_fatigue(**patch))


@pytest.mark.parametrize(
    "signals",
    [
        {"Bad-Key": 1},
        {"UPPER": 2},
        {"has space": 3},
        {"x" * 65: 1},
    ],
)
def test_signal_keys_are_bounded_identifiers(signals: dict) -> None:
    with pytest.raises(ValidationError):
        parse_sense_message(_fatigue(signals=signals))


def test_signals_are_scalar_only() -> None:
    with pytest.raises(ValidationError):
        parse_sense_message(_fatigue(signals={"nested": {"x": 1}}))
    with pytest.raises(ValidationError):
        parse_sense_message(_fatigue(signals={"listy": [1, 2]}))
