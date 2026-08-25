"""Single source of truth for the device⇄server wire contract.

Every contract constant exchanged across the cluster — LiveKit data-channel
topic names, the session-level metadata enums (interaction mode / session
intent), the ``session_end`` reason taxonomy, the ``client.audio_state`` field
vocabulary, and the device control-op names — is defined HERE and imported by
``eidolon_hub`` and ``eidolon_channel`` (both depend on ``eidolon-sdk``).

Why one place: these strings used to be hand-copied across hub (py), channel
(py), web (ts) and esp32 (c++). A single typo (``ppt`` vs ``ptt``) degraded
silently. Centralizing them is the platform foundation that makes adding a new
device a matter of *declaring capability*, not chasing scattered literals.

Non-Python clients keep lightweight language-native mirrors of this module.
Cross-repository contract tests keep those mirrors aligned with this source.

This module is pure constants, frozenset validity sets, and normalization
helpers — no imports from other ``eidolon_sdk`` submodules — so it can never
introduce an import cycle.
"""

from __future__ import annotations

from typing import Literal

# Bump when the on-wire JSON envelope shape changes in a backward-incompatible
# way. Carried as ``schema_v`` on messages (Track A3) so receivers can fail
# loud on a version they do not understand instead of silently mis-parsing.
WIRE_SCHEMA_VERSION = 1

# --------------------------------------------------------------------------- #
# LiveKit data-channel topics                                                  #
# --------------------------------------------------------------------------- #
# Device → server.
CLIENT_AUDIO_STATE_TOPIC = "eidolon.audio_state"
# Server → device.
# CONTROL_TOPIC is the device command bus. The envelope ``src.type`` decides the
# control plane:
#   - hub: cross-session device control with command history/ack/result.
#   - channel: session-local best-effort control inside the current voice room.
CONTROL_TOPIC = "eidolon.control"
EVENT_TOPIC = "eidolon.event"
COMPANION_UI_STATE_TOPIC = "eidolon.ui_state"
SESSION_CONTROL_TOPIC = "eidolon.session_control"

# LiveKit Agents framework data-stream topics. These are SDK-level contract
# constants because device and bridge participants subscribe to them directly;
# a LiveKit SDK upgrade changing one of these names must fail loudly in tests.
LIVEKIT_TRANSCRIPTION_TOPIC = "lk.transcription"
LIVEKIT_AGENT_SESSION_TOPIC = "lk.agent.session"

# --------------------------------------------------------------------------- #
# Session metadata bus — stamped by hub into LiveKit participant_metadata,     #
# resolved once by channel before AgentSession construction.                   #
# --------------------------------------------------------------------------- #
# interaction_mode: the duplex profile of the session. Three modes:
#   full_duplex — open mic + device AEC + barge-in (user can interrupt the agent).
#                 Device has a validated AEC reference (e.g. esp-box-3).
#   half_duplex — auto-record after session start (no button), NO device AEC; the
#                 mic is closed while the agent speaks (not interruptible). STT is
#                 committed via the same end-of-turn (EOT) judgment as full_duplex.
#                 For boards without a clean AEC reference (e.g. m5stack-stackchan).
#   ptt         — push-to-talk: mic open only while the device button is held;
#                 button release is the explicit end-of-turn. Mic closed otherwise.
#                 For wearables / button devices (e.g. waveshare 2.06).
# NOTE: half_duplex previously WAS push-to-talk; ptt is now its own mode and
# half_duplex means auto-record-no-barge-in. All producers/consumers (device
# firmware header, hub stamping, channel routing) must agree in lockstep.
INTERACTION_MODE_HALF_DUPLEX = "half_duplex"
INTERACTION_MODE_FULL_DUPLEX = "full_duplex"
INTERACTION_MODE_PTT = "ptt"
VALID_INTERACTION_MODES = frozenset(
    {INTERACTION_MODE_HALF_DUPLEX, INTERACTION_MODE_FULL_DUPLEX, INTERACTION_MODE_PTT}
)
InteractionMode = Literal["half_duplex", "full_duplex", "ptt"]

# session_intent: why this voice session exists.
#   user_initiated      — explicit user JOIN; canned welcome + normal idle.
#   presence_initiated  — verified owner-presence wake; canned welcome +
#                         externally governed renewable owner lease.
#   proactive_initiated — a report/action opens the session; no canned welcome.
SESSION_INTENT_FIELD = "session_intent"
SESSION_FLOW_ID_FIELD = "session_flow_id"
SESSION_INTENT_USER_INITIATED = "user_initiated"
SESSION_INTENT_PRESENCE = "presence_initiated"
SESSION_INTENT_PROACTIVE = "proactive_initiated"
VALID_SESSION_INTENTS = frozenset(
    {
        SESSION_INTENT_USER_INITIATED,
        SESSION_INTENT_PRESENCE,
        SESSION_INTENT_PROACTIVE,
    }
)
SessionIntent = Literal[
    "user_initiated",
    "presence_initiated",
    "proactive_initiated",
]


def normalize_session_intent(
    raw: str | None, *, default: str = SESSION_INTENT_USER_INITIATED
) -> str:
    """Resolve an untrusted wire value to a supported session intent.

    Missing and unknown values deliberately degrade to a normal user-driven
    session. Proactive behavior must always be explicitly requested.
    """

    candidate = (raw or "").strip().lower()
    return candidate if candidate in VALID_SESSION_INTENTS else default


def normalize_session_flow_id(raw: str | None) -> str | None:
    """Bound an optional cross-device correlation id for session metadata."""

    candidate = (raw or "").strip()
    if not candidate or len(candidate) > 96:
        return None
    return candidate


# --------------------------------------------------------------------------- #
# session_end — server → device teardown notice (eidolon.session_control).     #
# Client maps reason → UI ("已结束待命中" vs error). First reason wins.         #
# --------------------------------------------------------------------------- #
SESSION_END_TYPE = "session_end"
SESSION_END_IDLE_NORMAL = "idle_normal_end"
SESSION_END_USER_LEFT = "user_left"
SESSION_END_ERROR = "error"
SESSION_END_PROACTIVE_DONE = "proactive_done"
SESSION_END_SUPERSEDED = "superseded"
VALID_SESSION_END_REASONS = frozenset(
    {
        SESSION_END_IDLE_NORMAL,
        SESSION_END_USER_LEFT,
        SESSION_END_ERROR,
        SESSION_END_PROACTIVE_DONE,
        SESSION_END_SUPERSEDED,
    }
)
SessionEndReason = Literal[
    "idle_normal_end", "user_left", "error", "proactive_done", "superseded"
]

# --------------------------------------------------------------------------- #
# session_open / session_close — device → server, on eidolon.session_control.  #
# The other direction of the topic above.                                      #
# --------------------------------------------------------------------------- #
# A device holds its channel open for as long as it is enrolled, so being
# connected no longer says anything about wanting to talk. These are how a
# device says it — and stops saying it — which is what an agent, its models and
# its metered speech services are started and stopped by.
#
# Statements of desired state, not events: repeating one is not an error and
# does not stack, so a device that retries after a lost reply is safe.
SESSION_OPEN_TYPE = "session_open"
SESSION_CLOSE_TYPE = "session_close"
SESSION_STARTED_TYPE = "session_started"
SESSION_CONVERSATION_ID_FIELD = "conversation_id"
SESSION_CONVERSATION_ID_MAX_LENGTH = 64
VALID_SESSION_REQUEST_TYPES = frozenset({SESSION_OPEN_TYPE, SESSION_CLOSE_TYPE})
SessionRequestType = Literal["session_open", "session_close"]


def normalize_conversation_id(raw: str | None) -> str | None:
    """Validate the correlation key for one conversation inside a channel."""

    candidate = (raw or "").strip()
    if not candidate or len(candidate) > SESSION_CONVERSATION_ID_MAX_LENGTH:
        return None
    if not candidate.isascii() or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:"
        for char in candidate
    ):
        return None
    return candidate

# --------------------------------------------------------------------------- #
# client.audio_state — device → server observe-only signal vocabulary.         #
# --------------------------------------------------------------------------- #
# Payload "type" label inside the JSON body, decoupled from the routing topic.
CLIENT_AUDIO_STATE_TYPE = "client.audio_state"

INPUT_MODE_AUTO = "auto"
INPUT_MODE_PTT = "ptt"
INPUT_MODE_MANUAL = "manual"
INPUT_MODE_UNKNOWN = "unknown"
# Modes a client may legitimately declare (UNKNOWN is the parse fallback only).
VALID_INPUT_MODES = frozenset(
    {INPUT_MODE_AUTO, INPUT_MODE_PTT, INPUT_MODE_MANUAL}
)
InputMode = Literal["auto", "ptt", "manual", "unknown"]

PLAYBACK_STATE_IDLE = "idle"
PLAYBACK_STATE_AGENT_SPEAKING = "agent_speaking"
PLAYBACK_STATE_UNKNOWN = "unknown"
VALID_PLAYBACK_STATES = frozenset(
    {PLAYBACK_STATE_IDLE, PLAYBACK_STATE_AGENT_SPEAKING}
)
PlaybackState = Literal["idle", "agent_speaking", "unknown"]

# Every key a client may legitimately put in a client.audio_state body. The
# parser validates against this so a typo (``ppt`` instead of ``ptt``) is caught
# loudly instead of silently ignored.
CLIENT_AUDIO_STATE_KNOWN_KEYS = frozenset(
    {
        "type",
        "schema_v",
        "seq",
        "input_mode",
        "ptt",
        "manual_interrupt",
        "playback_state",
        "mic_muted",
        "rms",
        "snr_hint",
        "client_ts_ms",
    }
)

# --------------------------------------------------------------------------- #
# Device control ops — carried as ``op`` in the eidolon.control envelope.      #
# --------------------------------------------------------------------------- #
CONTROL_OP_ROOM_JOIN = "room.join"
CONTROL_OP_PLAYBACK_STOP = "playback.stop"
CONTROL_OP_PTT_TURN_STATUS = "ptt.turn_status"
CONTROL_OP_CONFIG_REFRESH = "config.refresh"
CONTROL_OP_DEVICE_IDENTIFY = "device.identify"
CONTROL_OP_DEVICE_ROLL_CALL = "device.roll_call"
# Device-local diagnostic for an ATK guard. It samples only local camera frames
# and returns aggregate measurements over the command-result channel.
CONTROL_OP_GUARD_VISION_BENCHMARK = "guard.vision.benchmark"
# Binding-local runtime reconciliation. The command contains only a desired
# state and revision; the device obtains its parameters from the signed Guard
# runtime-config pull endpoint.
CONTROL_OP_GUARD_RUNTIME_SYNC = "guard.runtime.sync"
# Owner-level profile reconciliation. The command is media-free; the device
# pulls its manifest and opaque references from signed Guard endpoints.
CONTROL_OP_GUARD_OWNER_FACE_PROFILE_SYNC = "guard.owner_face_profile.sync"
VALID_CONTROL_OPS = frozenset(
    {
        CONTROL_OP_ROOM_JOIN,
        CONTROL_OP_PLAYBACK_STOP,
        CONTROL_OP_PTT_TURN_STATUS,
        CONTROL_OP_CONFIG_REFRESH,
        CONTROL_OP_DEVICE_IDENTIFY,
        CONTROL_OP_DEVICE_ROLL_CALL,
        CONTROL_OP_GUARD_VISION_BENCHMARK,
        CONTROL_OP_GUARD_RUNTIME_SYNC,
        CONTROL_OP_GUARD_OWNER_FACE_PROFILE_SYNC,
    }
)
CONTROL_OP_ALIASES = frozenset(
    {
        ("wake", CONTROL_OP_ROOM_JOIN),
        ("refresh_config", CONTROL_OP_CONFIG_REFRESH),
        ("identify", CONTROL_OP_DEVICE_IDENTIFY),
    }
)
