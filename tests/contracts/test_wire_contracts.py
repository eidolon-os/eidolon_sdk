"""Stability guard for the device⇄server wire contract (single source).

These string values are baked into shipped firmware (ESP32 C++) and the web
client (TS). Changing one here without coordinating an exported-constant update
(Track A2) silently breaks every client. This test pins them so such a change
fails loudly in CI instead.
"""

from __future__ import annotations

from eidolon_sdk.biz import contracts as c


def test_topic_names_are_stable() -> None:
    assert c.CLIENT_AUDIO_STATE_TOPIC == "eidolon.audio_state"
    assert c.CONTROL_TOPIC == "eidolon.control"
    assert c.COMPANION_UI_STATE_TOPIC == "eidolon.ui_state"
    assert c.SESSION_CONTROL_TOPIC == "eidolon.session_control"
    assert c.LIVEKIT_TRANSCRIPTION_TOPIC == "lk.transcription"
    assert c.LIVEKIT_AGENT_SESSION_TOPIC == "lk.agent.session"


def test_session_metadata_enums_are_stable() -> None:
    assert c.INTERACTION_MODE_HALF_DUPLEX == "half_duplex"
    assert c.INTERACTION_MODE_FULL_DUPLEX == "full_duplex"
    assert c.INTERACTION_MODE_PTT == "ptt"
    assert c.VALID_INTERACTION_MODES == {"half_duplex", "full_duplex", "ptt"}
    assert c.SESSION_INTENT_FIELD == "session_intent"
    assert c.SESSION_INTENT_USER_INITIATED == "user_initiated"
    assert c.SESSION_INTENT_PROACTIVE == "proactive_initiated"
    assert c.VALID_SESSION_INTENTS == {"user_initiated", "proactive_initiated"}


def test_session_intent_normalization_is_defensive() -> None:
    assert c.normalize_session_intent(None) == c.SESSION_INTENT_USER_INITIATED
    assert c.normalize_session_intent("unknown") == c.SESSION_INTENT_USER_INITIATED
    assert c.normalize_session_intent(" PROACTIVE_INITIATED ") == c.SESSION_INTENT_PROACTIVE


def test_session_end_reasons_are_stable() -> None:
    assert c.SESSION_END_TYPE == "session_end"
    assert c.VALID_SESSION_END_REASONS == {
        "idle_normal_end",
        "user_left",
        "error",
        "proactive_done",
        "superseded",
    }


def test_audio_state_vocabulary_is_stable() -> None:
    assert c.CLIENT_AUDIO_STATE_TYPE == "client.audio_state"
    assert c.VALID_INPUT_MODES == {"auto", "ptt", "manual"}
    assert c.VALID_PLAYBACK_STATES == {"idle", "agent_speaking"}


def test_control_ops_are_stable() -> None:
    assert c.CONTROL_OP_ROOM_JOIN == "room.join"
    assert c.CONTROL_OP_PLAYBACK_STOP == "playback.stop"
    assert c.CONTROL_OP_PTT_TURN_STATUS == "ptt.turn_status"
    assert c.CONTROL_OP_CONFIG_REFRESH == "config.refresh"
    assert c.CONTROL_OP_DEVICE_IDENTIFY == "device.identify"
    assert c.CONTROL_OP_DEVICE_ROLL_CALL == "device.roll_call"
    assert c.CONTROL_OP_GUARD_VISION_BENCHMARK == "guard.vision.benchmark"
    assert c.CONTROL_OP_GUARD_RUNTIME_SYNC == "guard.runtime.sync"
    assert (
        c.CONTROL_OP_GUARD_OWNER_FACE_PROFILE_SYNC
        == "guard.owner_face_profile.sync"
    )
    assert c.VALID_CONTROL_OPS == {
        "room.join",
        "playback.stop",
        "ptt.turn_status",
        "config.refresh",
        "device.identify",
        "device.roll_call",
        "guard.vision.benchmark",
        "guard.runtime.sync",
        "guard.owner_face_profile.sync",
    }
    assert c.CONTROL_OP_ALIASES == {
        ("wake", "room.join"),
        ("refresh_config", "config.refresh"),
        ("identify", "device.identify"),
    }


def test_audio_state_known_keys_are_current_contract() -> None:
    # Every declared wire field is a known key.
    for field in (
        "input_mode",
        "ptt",
        "manual_interrupt",
        "playback_state",
        "mic_muted",
        "schema_v",
    ):
        assert field in c.CLIENT_AUDIO_STATE_KNOWN_KEYS


def test_wire_schema_version_is_an_int() -> None:
    assert isinstance(c.WIRE_SCHEMA_VERSION, int)
