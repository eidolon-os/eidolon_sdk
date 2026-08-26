"""Language-native client mirrors of the shared wire contract."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from eidolon_sdk.biz import contracts as c


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source(relative: str) -> str:
    path = _workspace_root() / relative
    if not path.exists():
        pytest.skip(f"client checkout is not present: {relative}")
    return path.read_text(encoding="utf-8")


def test_mobile_contract_mirror_matches_sdk() -> None:
    source = _source("eidolon_client_mobile/lib/src/protocol/eidolon_protocol.dart")
    constants = dict(re.findall(r"const\s+(\w+)\s*=\s*'([^']*)';", source))

    assert constants["controlOpRoomJoin"] == c.CONTROL_OP_ROOM_JOIN
    assert constants["sessionIntentField"] == c.SESSION_INTENT_FIELD
    assert constants["sessionIntentUserInitiated"] == c.SESSION_INTENT_USER_INITIATED
    assert constants["sessionIntentProactive"] == c.SESSION_INTENT_PROACTIVE
    # What a client says to be heard at all. Drift here is silent: the request
    # is published successfully and simply never recognised as one.
    assert constants["sessionControlTopic"] == c.SESSION_CONTROL_TOPIC
    assert constants["sessionOpenType"] == c.SESSION_OPEN_TYPE
    assert constants["sessionCloseType"] == c.SESSION_CLOSE_TYPE


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
