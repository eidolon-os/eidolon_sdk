"""ESP32 C++ mirror of the shared wire contract.

The Python constants in ``eidolon_sdk.biz.contracts`` are the source of truth,
while ESP32 firmware keeps a lightweight C++ mirror in ``eidolon_topics.h``.
This test reads that header directly in the multi-repo workspace so drift is
caught before flashing a device.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from eidolon_sdk.biz import contracts as c
from eidolon_sdk.biz import guard


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _esp32_topics_header() -> Path:
    return _workspace_root() / "eidolon-client-esp32/main/eidolon/eidolon_topics.h"


def _cpp_string_constants(header: str) -> dict[str, str]:
    return dict(
        re.findall(
            r'inline constexpr const char\*\s+(k\w+)\s*=\s*"([^"]*)";',
            header,
        )
    )


def _cpp_int_constants(header: str) -> dict[str, int]:
    return {
        name: int(value)
        for name, value in re.findall(
            r"inline constexpr int\s+(k\w+)\s*=\s*(\d+);",
            header,
        )
    }


def test_esp32_topics_header_matches_python_wire_contract() -> None:
    header_path = _esp32_topics_header()
    if not header_path.exists():
        pytest.skip("ESP32 client checkout is not present beside eidolon_sdk")

    header = header_path.read_text(encoding="utf-8")
    strings = _cpp_string_constants(header)
    ints = _cpp_int_constants(header)

    assert ints["kWireSchemaVersion"] == c.WIRE_SCHEMA_VERSION
    assert strings["kControlTopic"] == c.CONTROL_TOPIC
    assert strings["kClientAudioStateTopic"] == c.CLIENT_AUDIO_STATE_TOPIC
    assert strings["kUiStateTopic"] == c.COMPANION_UI_STATE_TOPIC
    assert strings["kSessionControlTopic"] == c.SESSION_CONTROL_TOPIC
    assert strings["kTranscriptionTopic"] == c.LIVEKIT_TRANSCRIPTION_TOPIC
    assert strings["kAgentSessionTopic"] == c.LIVEKIT_AGENT_SESSION_TOPIC

    assert strings["kClientAudioStateType"] == c.CLIENT_AUDIO_STATE_TYPE
    assert strings["kInputModeAuto"] == c.INPUT_MODE_AUTO
    assert strings["kInputModePtt"] == c.INPUT_MODE_PTT
    assert strings["kInputModeManual"] == c.INPUT_MODE_MANUAL
    assert strings["kPlaybackStateIdle"] == c.PLAYBACK_STATE_IDLE
    assert strings["kPlaybackStateAgentSpeaking"] == c.PLAYBACK_STATE_AGENT_SPEAKING

    assert strings["kControlOpRoomJoin"] == c.CONTROL_OP_ROOM_JOIN
    assert strings["kControlOpPlaybackStop"] == c.CONTROL_OP_PLAYBACK_STOP
    assert strings["kControlOpPttTurnStatus"] == c.CONTROL_OP_PTT_TURN_STATUS
    assert strings["kControlOpConfigRefresh"] == c.CONTROL_OP_CONFIG_REFRESH
    assert strings["kControlOpGuardRuntimeSync"] == c.CONTROL_OP_GUARD_RUNTIME_SYNC
    assert strings["kControlOpDeviceIdentify"] == c.CONTROL_OP_DEVICE_IDENTIFY
    assert strings["kGuardPresenceCandidateType"] == guard.GUARD_PRESENCE_CANDIDATE_TYPE
    assert strings["kGuardPresenceAbsentType"] == guard.GUARD_PRESENCE_ABSENT_TYPE

    assert strings["kInteractionModeHalfDuplex"] == c.INTERACTION_MODE_HALF_DUPLEX
    assert strings["kInteractionModeFullDuplex"] == c.INTERACTION_MODE_FULL_DUPLEX
    assert strings["kSessionIntentUserInitiated"] == c.SESSION_INTENT_USER_INITIATED
    assert strings["kSessionIntentProactive"] == c.SESSION_INTENT_PROACTIVE
