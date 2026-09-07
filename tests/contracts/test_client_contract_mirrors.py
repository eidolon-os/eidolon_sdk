"""Language-native client mirrors of the shared wire contract."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from eidolon_sdk.biz import contracts as c

import _session_vocabulary


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source(relative: str) -> str:
    path = _workspace_root() / relative
    if not path.exists():
        pytest.skip(f"client checkout is not present: {relative}")
    return path.read_text(encoding="utf-8")


def test_mobile_contract_mirror_matches_sdk() -> None:
    """Every session name this contract publishes, decided one way or the other.

    A roll-call could not catch the name that had just been added, and this
    mirror is where that cost twelve days — see `_session_vocabulary`.
    """

    source = _source("eidolon_client_mobile/lib/src/protocol/eidolon_protocol.dart")
    constants = dict(re.findall(r"const\s+(\w+)\s*=\s*'([^']*)';", source))
    integers = {
        name: int(value)
        for name, value in re.findall(r"const\s+(\w+)\s*=\s*(\d+);", source)
    }

    assert constants["controlOpRoomJoin"] == c.CONTROL_OP_ROOM_JOIN

    mirrored = {
        # What a client says to be heard at all. Drift here is silent: the
        # request is published successfully and simply never recognised as one.
        "SESSION_CONTROL_TOPIC": "sessionControlTopic",
        "SESSION_OPEN_TYPE": "sessionOpenType",
        "SESSION_CLOSE_TYPE": "sessionCloseType",
        "SESSION_CONVERSATION_ID_FIELD": "sessionConversationIdField",
        "SESSION_STARTED_TYPE": "sessionStartedType",
        "SESSION_END_TYPE": "sessionEndType",
        "SESSION_INTENT_FIELD": "sessionIntentField",
        "SESSION_INTENT_USER_INITIATED": "sessionIntentUserInitiated",
        "SESSION_INTENT_PROACTIVE": "sessionIntentProactive",
    }
    unmirrored = {
        "SESSION_INTENT_PRESENCE": (
            "a presence-initiated session is opened by a Body that can sense a room; this "
            "client opens sessions from a tap"
        ),
        "SESSION_END_ERROR": "the end reasons are read by whoever reports them, and this "
        "client reports none — it shows the session ended, not why",
        "SESSION_END_IDLE_NORMAL": "as SESSION_END_ERROR",
        "SESSION_END_PROACTIVE_DONE": "as SESSION_END_ERROR",
        "SESSION_END_SUPERSEDED": "as SESSION_END_ERROR",
        "SESSION_END_USER_LEFT": "as SESSION_END_ERROR",
        "SESSION_FLOW_ID_FIELD": "carried between Host services, never by a client",
        "SESSION_CONVERSATION_ID_MAX_LENGTH": (
            "a bound the Provider enforces on what it receives; a client that enforced it "
            "too would refuse an id the Provider would have accepted"
        ),
        "WIRE_SCHEMA_VERSION": "mirrored as an integer, asserted below rather than as a string",
    }
    _session_vocabulary.assert_every_name_is_decided(
        client="mobile", mirrored=mirrored, unmirrored=unmirrored
    )
    for contract_name, dart_name in mirrored.items():
        assert constants[dart_name] == getattr(c, contract_name), contract_name

    assert integers["sessionControlSchemaVersion"] == c.WIRE_SCHEMA_VERSION


def test_mobile_mission_control_mirror_matches_sdk() -> None:
    """Mobile's Mission Control vocabulary against this package's.

    Skips while the client checkout does not carry the file yet — the same
    arrangement as the mirrors above, and the reason this can be written before
    the branch that adds it lands.
    """

    from eidolon_sdk.biz.contracts import mission_control as mc

    source = _source(
        "eidolon_client_mobile/lib/src/protocol/mission_control_contract.dart"
    )

    scalars = dict(re.findall(r"const\s+(\w+)\s*=\s*'([^']*)';", source))
    assert scalars["missionControlContractVersion"] == mc.CONTRACT_VERSION
    assert scalars["missionControlSnapshotCoverage"] == mc.SNAPSHOT_COVERAGE
    assert scalars["laneStateOk"] == mc.LANE_OK
    assert scalars["laneStateDegraded"] == mc.LANE_DEGRADED
    assert scalars["laneStateUnavailable"] == mc.LANE_UNAVAILABLE
    assert scalars["presenceOnline"] == mc.PRESENCE_ONLINE
    assert scalars["presenceOffline"] == mc.PRESENCE_OFFLINE
    assert scalars["presenceDegraded"] == mc.PRESENCE_DEGRADED
    assert scalars["presenceUnknown"] == mc.PRESENCE_UNKNOWN
    assert scalars["presenceSourceBlackboard"] == mc.PRESENCE_SOURCE_BLACKBOARD
    assert scalars["presenceSourceHub"] == mc.PRESENCE_SOURCE_HUB
    assert scalars["presenceSourceNone"] == mc.PRESENCE_SOURCE_NONE
    assert scalars["cursorField"] == mc.CURSOR_FIELD
    assert scalars["streamResetEvent"] == mc.STREAM_RESET_EVENT

    def _literals(name: str) -> list[str]:
        """Members of a Dart set/list literal, whether spelled out or referenced.

        The mirror composes some of its sets from the constants above it rather
        than repeating the strings, which is the right way to write it and the
        wrong thing to read with a bare string-literal regex — the first version
        of this test read those sets as empty and passed. So an element is either
        a quoted literal or an identifier resolved through the scalars.
        """

        block = re.search(
            rf"const\s+{name}\s*=\s*<String>[\{{\[](.*?)[\}}\]];",
            source,
            re.DOTALL,
        )
        assert block, f"{name} is missing from the Dart mirror"
        members: list[str] = []
        for token in re.findall(r"'([^']*)'|([A-Za-z_]\w*)", block.group(1)):
            literal, identifier = token
            if literal:
                members.append(literal)
                continue
            assert identifier in scalars, (
                f"{name} references {identifier}, which is not a mirrored constant"
            )
            members.append(scalars[identifier])
        assert members, f"{name} came out empty — the mirror was not read"
        return members

    # Sets compare as sets; the stage list is ordered on purpose and compares
    # as a set too, because request order is documented by the SDK tuple and a
    # consumer that reorders its own copy is not thereby wrong.
    assert set(_literals("laneStates")) == mc.LANE_STATES
    assert set(_literals("presenceStates")) == mc.PRESENCE_STATES
    assert set(_literals("presenceSources")) == mc.PRESENCE_SOURCES
    assert set(_literals("roleKinds")) == mc.ROLE_KINDS
    assert set(_literals("activityKinds")) == mc.ACTIVITY_KINDS
    assert set(_literals("hopNodeTypes")) == mc.HOP_NODE_TYPES
    assert set(_literals("hopDirections")) == mc.HOP_DIRECTIONS
    assert set(_literals("serviceTiers")) == mc.SERVICE_TIERS
    assert set(_literals("outcomes")) == mc.OUTCOMES
    assert set(_literals("severities")) == mc.SEVERITIES
    assert set(_literals("privacyClasses")) == mc.PRIVACY_CLASSES
    assert set(_literals("eventOrigins")) == mc.EVENT_ORIGINS
    assert set(_literals("stageKeys")) == set(mc.STAGE_KEYS)


def test_mobile_companion_lifecycle_mirror_matches_sdk() -> None:
    """The Companion lifecycle vocabulary, checked where it actually lives.

    Not in the Mission Control mirror. These values belong to the Companion
    authority and the client's management surface consumes them too, so that
    client keeps them in its own companion contract — the same move this package
    made when it took them out of ``mission_control`` and into ``companion``. A
    mirror test left pointing at the old file would keep passing while checking
    nothing.
    """

    from eidolon_sdk.biz.contracts import companion as companion_contract

    source = _source(
        "eidolon_client_mobile/lib/src/protocol/companion_contract.dart"
    )
    scalars = dict(re.findall(r"const\s+(\w+)\s*=\s*'([^']*)';", source))
    block = re.search(
        r"const\s+companionLifecycleStates\s*=\s*<String>\{(.*?)\};",
        source,
        re.DOTALL,
    )
    assert block, "companionLifecycleStates is missing from the Dart mirror"

    members: list[str] = []
    for literal, identifier in re.findall(
        r"'([^']*)'|([A-Za-z_]\w*)", block.group(1)
    ):
        if literal:
            members.append(literal)
            continue
        assert identifier in scalars, f"{identifier} is not a mirrored constant"
        members.append(scalars[identifier])
    assert members, "the mirror read as empty, which is never agreement"

    assert set(members) == set(companion_contract.COMPANION_LIFECYCLE_STATES)
    # What a previous version of that mirror invented. No Host sends these.
    assert not {"pending", "suspended", "removed"} & set(members)
