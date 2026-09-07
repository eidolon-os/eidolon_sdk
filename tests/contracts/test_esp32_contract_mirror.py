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
from eidolon_sdk.biz import events
from eidolon_sdk.biz import guard

import _session_vocabulary


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _esp32_topics_header() -> Path:
    return _workspace_root() / "eidolon-client-esp32/main/eidolon/eidolon_topics.h"


def _esp32_source(relative: str) -> str:
    """As `_source` in test_client_contract_mirrors: absent repository skips,
    absent file inside a present repository fails. A mirror that goes on
    skipping after the file it mirrors was renamed is green over nothing."""

    repository = _workspace_root() / "eidolon-client-esp32"
    path = repository / relative
    if path.exists():
        return path.read_text(encoding="utf-8")
    if not repository.exists():
        pytest.skip("ESP32 client checkout is not present beside eidolon_sdk")
    raise AssertionError(
        f"eidolon-client-esp32 is present but does not carry {relative} — the mirrored file "
        "moved, and a mirror that skips after a rename never goes red again"
    )


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
    header = _esp32_source("main/eidolon/eidolon_topics.h")
    strings = _cpp_string_constants(header)
    ints = _cpp_int_constants(header)

    assert ints["kWireSchemaVersion"] == c.WIRE_SCHEMA_VERSION
    assert ints["kDeviceEventSchemaVersion"] == events.EVENT_SCHEMA_VERSION
    assert strings["kControlTopic"] == c.CONTROL_TOPIC
    assert strings["kEventTopic"] == c.EVENT_TOPIC
    assert strings["kAmbientPresenceStateType"] == events.AMBIENT_PRESENCE_STATE_TYPE
    assert (
        strings["kIdentityOwnerPresenceConfirmedType"]
        == events.IDENTITY_OWNER_PRESENCE_CONFIRMED_TYPE
    )
    assert strings["kClientAudioStateTopic"] == c.CLIENT_AUDIO_STATE_TOPIC
    assert strings["kUiStateTopic"] == c.COMPANION_UI_STATE_TOPIC
    assert strings["kTranscriptionTopic"] == c.LIVEKIT_TRANSCRIPTION_TOPIC
    assert strings["kAgentSessionTopic"] == c.LIVEKIT_AGENT_SESSION_TOPIC

    # What a device says to be heard at all. Drift here is silent: the request
    # is published successfully and simply never recognised as one. Decided as
    # a whole vocabulary rather than named one at a time — a roll-call cannot
    # catch the name that was just added, which is what it cost the other
    # client's mirror. See `_session_vocabulary`.
    mirrored = {
        "SESSION_CONTROL_TOPIC": "kSessionControlTopic",
        "SESSION_OPEN_TYPE": "kSessionOpenType",
        "SESSION_CLOSE_TYPE": "kSessionCloseType",
        "SESSION_STARTED_TYPE": "kSessionStartedType",
        "SESSION_CONVERSATION_ID_FIELD": "kSessionConversationIdField",
        "SESSION_END_TYPE": "kSessionEndType",
        "SESSION_END_ERROR": "kSessionEndError",
        "SESSION_END_IDLE_NORMAL": "kSessionEndIdleNormal",
        "SESSION_END_PROACTIVE_DONE": "kSessionEndProactiveDone",
        "SESSION_END_SUPERSEDED": "kSessionEndSuperseded",
        "SESSION_END_USER_LEFT": "kSessionEndUserLeft",
        "SESSION_INTENT_FIELD": "kSessionIntentField",
        "SESSION_INTENT_USER_INITIATED": "kSessionIntentUserInitiated",
        "SESSION_INTENT_PRESENCE": "kSessionIntentPresence",
        "SESSION_INTENT_PROACTIVE": "kSessionIntentProactive",
    }
    unmirrored = {
        "SESSION_FLOW_ID_FIELD": (
            "this firmware carries the flow id in the X-Device-Session-Flow-Id header, not "
            "as a payload member, and kSessionFlowIdHeader is that header's name rather than "
            "a mirror of this one"
        ),
        "SESSION_CONVERSATION_ID_MAX_LENGTH": (
            "a bound the Provider enforces on what it receives; a device that enforced it too "
            "would refuse an id the Provider would have accepted"
        ),
        "WIRE_SCHEMA_VERSION": "mirrored as an integer, asserted above rather than as a string",
    }
    _session_vocabulary.assert_every_name_is_decided(
        client="esp32", mirrored=mirrored, unmirrored=unmirrored
    )
    _session_vocabulary.assert_mirrored(
        client="esp32",
        declared=strings,
        mirrored=mirrored,
        source="eidolon_topics.h",
    )

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
    assert strings["kControlOpDeviceRollCall"] == c.CONTROL_OP_DEVICE_ROLL_CALL
    assert strings["kGuardPresenceCandidateType"] == guard.GUARD_PRESENCE_CANDIDATE_TYPE
    assert strings["kGuardPresenceAbsentType"] == guard.GUARD_PRESENCE_ABSENT_TYPE
    assert strings["kGuardOwnerPresenceType"] == guard.GUARD_OWNER_PRESENCE_TYPE

    assert strings["kInteractionModeHalfDuplex"] == c.INTERACTION_MODE_HALF_DUPLEX
    assert strings["kInteractionModeFullDuplex"] == c.INTERACTION_MODE_FULL_DUPLEX
    assert strings["kInteractionModePtt"] == c.INTERACTION_MODE_PTT
    assert strings["kSessionIntentUserInitiated"] == c.SESSION_INTENT_USER_INITIATED
    assert strings["kSessionIntentPresence"] == c.SESSION_INTENT_PRESENCE
    assert strings["kSessionIntentProactive"] == c.SESSION_INTENT_PROACTIVE


def test_esp32_canonical_claim_consumer_and_roll_call_handler_match_contract() -> None:
    hub_types = _esp32_source("main/eidolon/hub_types.h")
    onboarding = _esp32_source("main/eidolon/hub_onboarding_protocol.cc")
    claim_core = _esp32_source("main/eidolon/device_claim_consumer_core.cc")
    controller = _esp32_source("main/eidolon/eidolon_voice_controller.cc")
    feedback = _esp32_source("main/eidolon/eidolon_local_feedback.cc")

    assert 'kTxtOwnerDomainId = "owner_domain_id"' in hub_types
    assert '"owner_domain_descriptor_uri"' in hub_types
    assert "kTxtDescriptorUri" not in hub_types
    assert "kTxtEnrollmentUri" not in hub_types
    assert "kTxtRegisterUrl" not in hub_types
    assert "ParseHandoffResponse" not in onboarding
    assert "retrieval_token" not in onboarding
    assert "ClaimGrantAad" in claim_core
    assert "OpenClaimGrant" in claim_core
    assert "DestroyEnrollmentMaterial" in claim_core
    assert "ResumePending" in claim_core
    assert (
        "{kControlOpDeviceRollCall, 1, "
        "&EidolonVoiceController::HandleDeviceRollCallCommand}" in controller
    )
    assert "pending_session_intent_ = kSessionIntentPresence;" in controller
    assert "command.capability_version != entry.capability_version" in controller
    assert "PlayRollCallFeedback()" in controller
    assert 'AckCommand(command, "completed", "OK", "", "{\\"played\\":true}")' in controller
    assert "esp_err_t PlayRollCallFeedback()" in feedback


def test_esp32_validates_the_owner_route_from_the_signed_descriptor_uri() -> None:
    """The device must re-fetch the directory at the route the document states.

    Firmware once derived that route by appending "/descriptor" to the Admission
    endpoint base. No Host answers that path, so every commissioning ended in a
    rollback the Owner saw only as "configuration failed" — and every failure
    path of this step logged nothing, so no party could name the missing fact.
    """
    runtime = _esp32_source("main/eidolon/commissioning_runtime.cc")

    assert "HubHttpRequest(\"GET\", staged.descriptor_uri," in runtime
    assert 'endpoint.uri + "/descriptor"' not in runtime
    assert "LogicalAuthority::Admission" not in runtime
    # Every rejection names itself; a silent `return false` here is the defect.
    assert runtime.count("Owner route rejected") == 7
