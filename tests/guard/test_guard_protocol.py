from __future__ import annotations

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.guard import (
    GuardOwnerPresence,
    GuardPresenceCandidate,
    normalize_guard_policy_config,
    normalize_guard_runtime_config,
    parse_guard_message,
    parse_guard_policy_config,
    parse_guard_runtime_config,
)


def _owner_presence(*, state: str = "present", sequence: int = 1) -> dict:
    return {
        "type": "guard.owner_presence",
        "schema_v": 1,
        "guard_companion_id": "guard-owner-1",
        "device_id": "atk-1",
        "correlation_id": "op-boot1-r5-e3",
        "guard_epoch": 3,
        "ts_ms": 1_700_000_000_000,
        "state": state,
        "profile_revision": 5,
        "sequence": sequence,
        "lease_ms": 30_000 if state == "present" else 0,
        "raw_retention": "none",
    }


def _candidate() -> dict:
    return {
        "type": "guard.presence.candidate",
        "schema_v": 1,
        "guard_companion_id": "guard-owner-1",
        "device_id": "atk-1",
        "correlation_id": "corr-1",
        "guard_epoch": 2,
        "ts_ms": 1_700_000_000_000,
        "signals": {"motion_cells": 4, "motion_score": 0.42},
        "camera": {"frame_hash": "a" * 64, "motion_score": 0.42},
        "raw_retention": "none",
        "debounce_ms": 800,
    }


def test_candidate_contract_is_versioned_and_privacy_bounded() -> None:
    message = parse_guard_message(_candidate())
    assert isinstance(message, GuardPresenceCandidate)
    assert message.raw_retention == "none"


def test_owner_presence_contract_is_stateful_leased_and_privacy_bounded() -> None:
    message = parse_guard_message(_owner_presence())
    assert isinstance(message, GuardOwnerPresence)
    assert message.state == "present"
    assert message.lease_ms == 30_000

    absent = parse_guard_message(_owner_presence(state="absent", sequence=4))
    assert isinstance(absent, GuardOwnerPresence)
    assert absent.state == "absent"
    assert absent.lease_ms == 0


@pytest.mark.parametrize(
    "patch",
    [
        {"lease_ms": 0},
        {"state": "absent", "lease_ms": 30_000},
        {"profile_revision": 0},
        {"sequence": 0},
        {"owner_id": "owner-1"},
        {"similarity": 0.9},
        {"faces": 1},
    ],
)
def test_owner_presence_rejects_invalid_or_sensitive_shape(patch: dict) -> None:
    payload = _owner_presence()
    payload.update(patch)
    with pytest.raises(ValidationError):
        parse_guard_message(payload)


@pytest.mark.parametrize("field", ["raw_image", "audio", "face_embedding", "template"])
def test_guard_contract_rejects_sensitive_or_unknown_fields(field: str) -> None:
    payload = _candidate()
    payload[field] = "not allowed"
    with pytest.raises(ValidationError):
        parse_guard_message(payload)


def test_guard_contract_rejects_unknown_versions() -> None:
    payload = _candidate()
    payload["schema_v"] = 2
    with pytest.raises(ValidationError):
        parse_guard_message(payload)


def test_guard_protocol_rejects_unimplemented_verifier_and_action() -> None:
    verified = {
        **_candidate(),
        "type": "guard.presence.verified",
        "verifier": "channel",
        "verdict": "present",
    }
    with pytest.raises(ValidationError):
        parse_guard_message(verified)

    action = {
        "type": "guard.policy.action",
        "schema_v": 1,
        "guard_companion_id": "guard-owner-1",
        "device_id": "atk-1",
        "correlation_id": "corr-1",
        "guard_epoch": 2,
        "ts_ms": 1_700_000_000_000,
        "action_id": "action-1",
        "policy_id": "silent_presence",
        "action": "body.look_at",
    }
    with pytest.raises(ValidationError):
        parse_guard_message(action)


@pytest.mark.parametrize(
    "signals",
    [
        {"bad signal": 1},
        {f"signal_{index}": index for index in range(17)},
    ],
)
def test_guard_candidate_bounds_extension_telemetry(signals: dict) -> None:
    payload = _candidate()
    payload["signals"] = signals
    with pytest.raises(ValidationError):
        parse_guard_message(payload)


@pytest.mark.parametrize(
    "patch",
    [
        {"guard_epoch": "2"},
        {"ts_ms": "1700000000000"},
        {"signals": {"motion_cells": "4"}},
        {"signals": {"face_present": "true"}},
        {"camera": {"motion_score": "0.42"}},
        {"debounce_ms": "800"},
    ],
)
def test_guard_contract_rejects_string_coercion_for_numbers_and_bools(patch: dict) -> None:
    payload = _candidate()
    payload.update(patch)
    with pytest.raises(ValidationError):
        parse_guard_message(payload)


def test_silent_presence_policy_config_is_versioned_and_normalized() -> None:
    config = parse_guard_policy_config("silent_presence", {})
    assert config.schema_v == 1
    assert config.accepted_verdicts == ("present", "unknown")
    assert normalize_guard_policy_config("silent_presence", {}) == {
        "schema_v": 1,
        "candidate_enabled": True,
        "verified_enabled": True,
        "accepted_verdicts": ["present", "unknown"],
        "absence_enabled": True,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"candidate_enabled": "true"},
        {"verified_enabled": "false"},
        {"absence_enabled": "false"},
    ],
)
def test_silent_presence_policy_config_rejects_string_bools(payload: dict) -> None:
    with pytest.raises(ValueError):
        parse_guard_policy_config("silent_presence", payload)


@pytest.mark.parametrize(
    "policy_id,payload",
    [
        ("unknown_policy", {}),
        ("silent_presence", {"raw_image": "not allowed"}),
        ("silent_presence", {"accepted_verdicts": ["rejected"]}),
        ("silent_presence", {"accepted_verdicts": []}),
        ("silent_presence", {"accepted_verdicts": ["present", "present"]}),
        ("silent_presence", {"schema_v": 2}),
    ],
)
def test_silent_presence_policy_config_rejects_unsupported_or_sensitive_values(
    policy_id: str,
    payload: dict,
) -> None:
    with pytest.raises(ValueError):
        parse_guard_policy_config(policy_id, payload)


def test_guard_runtime_config_is_versioned_and_normalized() -> None:
    assert normalize_guard_runtime_config({}) == {
        "schema_v": 1,
        "sample_interval_ms": 500,
        "preview_interval_ms": 1000,
        "motion_threshold": 18,
        "motion_clear_threshold": 9,
        "candidate_debounce_ms": 1000,
        "absence_timeout_ms": 180000,
        "consecutive_capture_failures": 5,
        "owner_face_interval_ms": 1500,
        "owner_presence_enter_ms": 2500,
        "owner_presence_exit_ms": 12000,
        "owner_presence_heartbeat_ms": 10000,
        "owner_presence_lease_ms": 30000,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"sample_interval_ms": "500"},
        {"motion_threshold": "18"},
        {"consecutive_capture_failures": "5"},
    ],
)
def test_guard_runtime_config_rejects_string_numbers(payload: dict) -> None:
    with pytest.raises(ValueError):
        parse_guard_runtime_config(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"raw_image": "forbidden"},
        {"schema_v": 2},
        {"motion_clear_threshold": 19, "motion_threshold": 18},
        {"preview_interval_ms": 200, "sample_interval_ms": 500},
        {"candidate_debounce_ms": 200, "sample_interval_ms": 500},
        {"absence_timeout_ms": 500, "sample_interval_ms": 500},
    ],
)
def test_guard_runtime_config_rejects_unsafe_or_incoherent_values(payload: dict) -> None:
    with pytest.raises(ValueError):
        parse_guard_runtime_config(payload)
