import json

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.presentation.attention import (
    EVENT_NAME,
    LOCK_HOLD_LEASE_MS,
    LOCK_MAX_LEASE_MS,
    LOCK_MIN_LEASE_MS,
    LOCK_RELEASE_LEASE_MS,
    LOCK_TOPIC,
    SPEAKER_EVENT_NAME,
    SPEAKER_TOPIC,
    TOPIC,
    AttentionLock,
    AttentionSpeaker,
    AttentionState,
    manifest_event,
    speaker_manifest_event,
)
from eidolon_sdk.device_foundation.v1.lifecycle import ManifestEvent

SPEAKER_FIELDS = {
    "version", "session_id", "policy_revision", "sequence", "facts_sequence",
    "final", "track_id", "basis", "confidence", "in_view",
}
LOCK_FIELDS = {
    "version", "session_id", "policy_revision", "sequence", "phase", "turn_id",
    "track_id", "speaker_sequence", "lease_ms",
}


def speaker(**overrides):
    return dict(
        session_id="session-1", policy_revision=1, sequence=1, facts_sequence=41,
        final=True, track_id="k3", basis="face", confidence=0.8, in_view=True,
    ) | overrides


def lock(**overrides):
    return dict(
        session_id="session-1", policy_revision=1, sequence=1, phase="hold",
        turn_id="0123456789abcdef", track_id="k3", speaker_sequence=8,
        lease_ms=LOCK_HOLD_LEASE_MS,
    ) | overrides


def test_topics_are_separate_from_the_state_topic():
    assert TOPIC == "eidolon.attention.v1"
    assert SPEAKER_TOPIC == "eidolon.attention.speaker.v1"
    assert LOCK_TOPIC == "eidolon.attention.lock.v1"
    assert len({TOPIC, SPEAKER_TOPIC, LOCK_TOPIC}) == 3


def test_speaker_round_trips_and_its_wire_keys_are_exactly_the_field_table():
    message = AttentionSpeaker.model_validate(speaker())
    wire = message.model_dump_json()
    assert set(json.loads(wire)) == SPEAKER_FIELDS
    assert AttentionSpeaker.model_validate_json(wire) == message
    unattributed = AttentionSpeaker.model_validate(
        speaker(track_id=None, basis="none", confidence=0.0, in_view=False))
    assert set(json.loads(unattributed.model_dump_json())) == SPEAKER_FIELDS


def test_lock_round_trips_and_its_wire_keys_are_exactly_the_field_table():
    hold = AttentionLock.model_validate(lock())
    assert set(json.loads(hold.model_dump_json())) == LOCK_FIELDS
    assert AttentionLock.model_validate_json(hold.model_dump_json()) == hold
    release = AttentionLock(
        session_id="session-1", policy_revision=1, sequence=2, phase="release",
        lease_ms=LOCK_RELEASE_LEASE_MS)
    assert set(json.loads(release.model_dump_json())) == LOCK_FIELDS
    assert release.turn_id is release.track_id is release.speaker_sequence is None


@pytest.mark.parametrize("model,data", [(AttentionSpeaker, speaker()), (AttentionLock, lock())])
@pytest.mark.parametrize("extra", ["yaw_rad", "azimuth", "person_id", "ts_ms", "name"])
def test_unknown_fields_are_rejected(model, data, extra):
    with pytest.raises(ValidationError):
        model.model_validate(data | {extra: 1})
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(data | {extra: 1}))


@pytest.mark.parametrize("overrides", [
    {"version": 2},
    {"session_id": ""},
    {"session_id": "has space"},
    {"policy_revision": 0},
    {"sequence": 0},
    {"facts_sequence": 0},
    {"facts_sequence": "41"},
    {"final": "true"},
    {"final": 1},
    {"track_id": ""},
    {"track_id": "k" * 97},
    {"track_id": "k/3"},
    {"basis": "doa"},
    {"confidence": -0.01},
    {"confidence": 1.01},
    {"confidence": float("nan")},
    {"confidence": "0.5"},
    {"in_view": "yes"},
])
def test_speaker_field_bounds(overrides):
    with pytest.raises(ValidationError):
        AttentionSpeaker.model_validate(speaker(**overrides))


def test_speaker_accepts_its_boundary_values():
    AttentionSpeaker.model_validate(speaker(confidence=0, track_id="k" * 96))
    AttentionSpeaker.model_validate(speaker(confidence=1, basis="voice", in_view=False))
    AttentionSpeaker.model_validate(speaker(basis="none", track_id="k1", confidence=0.2))


@pytest.mark.parametrize("basis", ["face", "voice"])
def test_an_attribution_basis_needs_a_track(basis):
    with pytest.raises(ValidationError, match="SPEAKER_TRACK_REQUIRED"):
        AttentionSpeaker.model_validate(speaker(track_id=None, basis=basis))


@pytest.mark.parametrize("lease_ms", [LOCK_MIN_LEASE_MS, 1500, LOCK_MAX_LEASE_MS])
def test_lock_lease_accepts_the_documented_range(lease_ms):
    assert AttentionLock.model_validate(lock(lease_ms=lease_ms)).lease_ms == lease_ms


@pytest.mark.parametrize("lease_ms", [0, LOCK_MIN_LEASE_MS - 1, LOCK_MAX_LEASE_MS + 1, 1500.0, "1500"])
def test_lock_lease_outside_the_range_or_not_an_integer_is_rejected(lease_ms):
    with pytest.raises(ValidationError):
        AttentionLock.model_validate(lock(lease_ms=lease_ms))


def test_lock_lease_constants_are_the_contract_defaults():
    assert (LOCK_MIN_LEASE_MS, LOCK_MAX_LEASE_MS) == (500, 30000)
    assert (LOCK_HOLD_LEASE_MS, LOCK_RELEASE_LEASE_MS) == (30000, 1500)


@pytest.mark.parametrize("overrides", [
    {"phase": "lock"},
    {"sequence": 0},
    {"policy_revision": 0},
    {"turn_id": ""},
    {"speaker_sequence": 0},
    {"speaker_sequence": "8"},
])
def test_lock_field_bounds(overrides):
    with pytest.raises(ValidationError):
        AttentionLock.model_validate(lock(**overrides))


def test_a_lock_without_a_report_carries_no_track_but_a_track_needs_its_report():
    AttentionLock.model_validate(lock(track_id=None, speaker_sequence=None))
    AttentionLock.model_validate(lock(track_id=None, speaker_sequence=8))
    with pytest.raises(ValidationError, match="LOCK_SPEAKER_SEQUENCE_REQUIRED"):
        AttentionLock.model_validate(lock(speaker_sequence=None))


def test_messages_are_immutable():
    with pytest.raises(ValidationError):
        AttentionLock.model_validate(lock()).phase = "release"


def test_speaker_manifest_event_is_a_valid_manifest_entry_describing_the_wire():
    entry = speaker_manifest_event()
    assert entry["name"] == SPEAKER_EVENT_NAME == "attention.speaker"
    ManifestEvent.model_validate(entry)
    schema = entry["data_schema"]
    assert "title" not in schema and "description" not in schema
    assert set(schema["properties"]) == SPEAKER_FIELDS
    assert schema["additionalProperties"] is False


def test_state_manifest_event_is_unchanged_by_the_new_messages():
    entry = manifest_event()
    assert entry["name"] == EVENT_NAME == "attention.state"
    assert set(entry["data_schema"]["properties"]) == set(AttentionState.model_fields)
