"""Language-native client mirrors of the shared wire contract."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from eidolon_sdk.biz import contracts as c

import _session_vocabulary


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source(relative: str) -> str:
    """The client's mirror file, or a decision about why it cannot be read.

    Absent *repository* is a skip: an SDK-only checkout legitimately cannot
    verify a mirror. Absent *file inside a repository that is present* is a
    failure. That distinction is the point — before it, renaming
    `eidolon_protocol.dart` would have made this test skip silently and forever,
    which is the same "green while covering nothing" this file exists to refuse.
    """

    path = _workspace_root() / relative
    if path.exists():
        return path.read_text(encoding="utf-8")
    repository = _workspace_root() / Path(relative).parts[0]
    if not repository.exists():
        pytest.skip(f"client checkout is not present, so this mirror verifies nothing: {relative}")
    raise AssertionError(
        f"{repository.name} is present but does not carry {relative} — the mirrored file moved, "
        "and a mirror that skips after a rename never goes red again"
    )


#: Every repository that hand-writes this wire vocabulary, and what checks it.
#:
#: The client is the unit here, not the constant. Making the session vocabulary
#: exhaustive closed "a name nobody listed"; this closes the version one level
#: up — a *client* nobody listed. `eidolon_client_web` was exactly that: it has
#: declared `CONTROL_TOPIC` and `SESSION_CONTROL_TOPIC` in
#: `src/lib/contracts.ts` all along with nothing anywhere comparing them to this
#: package, and neither this file nor anyone's ledger knew it existed.
#:
#: A value of None means the mirror is known and unverified, with the reason
#: recorded. That is worse than verified and much better than invisible.
_WIRE_CONTRACT_MIRRORS: dict[str, str | None] = {
    "eidolon_client_mobile": "test_mobile_contract_mirror_matches_sdk",
    "eidolon-client-esp32": "test_esp32_topics_header_matches_python_wire_contract",
    "eidolon-client-esp32-korvo-1": "test_korvo_firmware_agrees_with_the_firmware_that_is_mirrored",
    "eidolon_client_web": None,
}

#: Names the korvo fork has not taken from the firmware it forked. Values may
#: never differ; a name may lag, and each lag is listed so that dropping one is
#: not the same as never having received it.
_KORVO_LAGS_BEHIND_ON = {
    "kSessionIntentField": (
        "added upstream on 2026-09-07 when that firmware stopped spelling the member at the "
        "read; this fork still spells it inline and has not taken the constant"
    ),
}

_UNVERIFIED_MIRRORS = {
    "eidolon_client_web": (
        "src/lib/contracts.ts mirrors this vocabulary by hand and nothing compares it. Not "
        "given a roll-call here on purpose: a third hand-maintained list would repeat the "
        "fault the other two are being moved off. It is waiting on the per-client ledger "
        "the mobile line already carries, where the contract is enumerated and each name "
        "must be decided."
    ),
}

#: Distinctive enough that finding one in a repository means that repository is
#: spelling this vocabulary. `SESSION_END_ERROR` is "error" and
#: `SESSION_CONVERSATION_ID_MAX_LENGTH` is 64; a scan that cried wolf on those
#: would be switched off within a day, and a check that gets switched off is
#: worse than one nobody wrote.
_DISTINCTIVE_VALUES = (
    "eidolon.session_control",
    "eidolon.control",
    "eidolon.audio_state",
    "client.audio_state",
)

_UNSCANNED = {".git", "node_modules", ".venv", "build", ".dart_tool", "vendor", ".worktrees"}


def _cpp_strings(header: str) -> dict[str, str]:
    return dict(
        re.findall(r'inline constexpr const char\*\s+(k\w+)\s*=\s*"([^"]*)";', header)
    )


def _repositories_spelling_this_vocabulary() -> set[str]:
    workspace = _workspace_root()
    found: set[str] = set()
    for repository in sorted(workspace.iterdir()):
        if not repository.is_dir() or repository.name.startswith("."):
            continue
        if repository.name == "eidolon_sdk":
            continue
        for directory, names, files in os.walk(repository):
            names[:] = [name for name in names if name not in _UNSCANNED]
            for name in files:
                if not name.endswith((".dart", ".ts", ".tsx", ".h", ".cc", ".kt", ".swift")):
                    continue
                text = (Path(directory) / name).read_text(encoding="utf-8", errors="ignore")
                if sum(value in text for value in _DISTINCTIVE_VALUES) >= 2:
                    found.add(repository.name)
                    break
            if repository.name in found:
                break
    return found


def test_every_client_that_mirrors_this_contract_is_accounted_for() -> None:
    """No client may spell this vocabulary without a decision recorded here.

    The mirrors below can only be as complete as the list of clients they cover,
    and that list was itself a roll-call. `eidolon_client_web` had been mirroring
    `eidolon.control` and `eidolon.session_control` with nothing checking them,
    which is the same failure as a constant nobody asserted, one level up.

    Skips only when there is no workspace to scan — an SDK-only checkout cannot
    know who its clients are, and saying so is honest where passing would not be.
    """

    workspace = _workspace_root()
    siblings = [p for p in workspace.iterdir() if p.is_dir() and p.name.startswith("eidolon")]
    if len(siblings) <= 1:
        pytest.skip("no client checkouts beside eidolon_sdk, so the roster verifies nothing")

    spelling = _repositories_spelling_this_vocabulary()
    unaccounted = sorted(spelling - set(_WIRE_CONTRACT_MIRRORS))
    assert not unaccounted, (
        f"{unaccounted} spell this wire vocabulary and no mirror here mentions them. Add a "
        "mirror, or record the repository as a known unverified one with the reason. A client "
        "nobody listed is the same defect as a constant nobody listed."
    )

    stale = sorted(
        repository
        for repository in _WIRE_CONTRACT_MIRRORS
        if (workspace / repository).is_dir() and repository not in spelling
    )
    assert not stale, (
        f"{stale} are listed as mirroring this vocabulary and no longer spell it — a decision "
        "about a client that stopped being one outlives the thing it was about"
    )

    undecided = sorted(
        repository
        for repository, test in _WIRE_CONTRACT_MIRRORS.items()
        if test is None and repository not in _UNVERIFIED_MIRRORS
    )
    assert not undecided, f"{undecided} have no mirror and no reason for not having one"

    for repository, reason in _UNVERIFIED_MIRRORS.items():
        assert reason.strip(), f"{repository} is excused without a reason"


def test_korvo_firmware_agrees_with_the_firmware_that_is_mirrored() -> None:
    """The fork's wire values against the fork's upstream, which is mirrored.

    `eidolon-client-esp32-korvo-1` carries its own `eidolon_topics.h` and nothing
    compared it to anything. Giving it a third roll-call against this package
    would repeat the fault; asserting instead that it agrees with the firmware
    that *is* mirrored costs a few lines and inherits the whole check — a value
    this fork drifts on goes red here, whichever side moved.

    Names are allowed to lag, because a fork receives changes later, and each
    lag is recorded. That is the difference between a fork that has not caught
    up and one that has quietly dropped something.
    """

    upstream = _cpp_strings(_source("eidolon-client-esp32/main/eidolon/eidolon_topics.h"))
    fork = _cpp_strings(_source("eidolon-client-esp32-korvo-1/main/eidolon/eidolon_topics.h"))

    disagree = sorted(
        f"{name}: upstream {upstream[name]!r}, fork {fork[name]!r}"
        for name in set(upstream) & set(fork)
        if upstream[name] != fork[name]
    )
    assert not disagree, "the korvo fork has drifted from the firmware that is mirrored: " + "; ".join(disagree)

    lagging = sorted(set(upstream) - set(fork))
    assert lagging == sorted(_KORVO_LAGS_BEHIND_ON), (
        f"the korvo fork lags on {lagging}, and the recorded lag is "
        f"{sorted(_KORVO_LAGS_BEHIND_ON)} — take the constant, or record why it is behind"
    )
    for name, reason in _KORVO_LAGS_BEHIND_ON.items():
        assert reason.strip(), f"{name} is recorded as lagging without a reason"

    ahead = sorted(set(fork) - set(upstream))
    assert not ahead, (
        f"the korvo fork declares {ahead}, which the mirrored firmware does not — a wire name "
        "that exists only on a fork is one no mirror can see"
    )


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
    _session_vocabulary.assert_mirrored(
        client="mobile",
        declared=constants,
        mirrored=mirrored,
        source="eidolon_protocol.dart",
    )

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
