"""Single source of truth for the Mission Control Local API vocabulary.

The Owner-scoped runtime projection Mobile reads (`GET
/api/local/v1/mission-control/snapshot` and its event stream) is produced by
`eidolon_admin`'s Local API and consumed by a Dart client that does not import
this package. So the enforcement is the same one the device wire contract uses:
the values live here, the JSON Schemas beside them in
``contracts/local_api/v1/``, and cross-repository tests keep the language-native
mirrors aligned with this module.

Three vocabularies here are *not* new. ``OUTCOMES``, ``SEVERITIES`` and
``PRIVACY_CLASSES`` are the audit envelope's own, restated rather than imported
so this module keeps its promise of importing nothing else from the SDK — and
pinned equal to the envelope by test, which is the same guard the rest of this
package relies on. A projection of an audit event that invented its own words
for "what happened" would be a second taxonomy for one fact.
"""

from __future__ import annotations

CONTRACT_VERSION = "1"

# What the snapshot claims to cover. Stated on the wire so a reader is never
# left inferring scope from the size of a list.
SNAPSHOT_COVERAGE = "owner-runtime"

# ── lane envelope ──────────────────────────────────────────────────────────
# Every projection block carries its own health. "Read it, it was empty" and
# "could not read it" are different states and must never share a shape:
# a failure that renders as an empty list is a screen that lies quietly.
LANE_OK = "ok"
LANE_DEGRADED = "degraded"
LANE_UNAVAILABLE = "unavailable"
LANE_STATES = frozenset({LANE_OK, LANE_DEGRADED, LANE_UNAVAILABLE})

# ── device presence ────────────────────────────────────────────────────────
# Presence has an authority and a precedence, and the projection carries both.
# `unknown` is neither online nor offline: it is nobody having answered.
PRESENCE_ONLINE = "online"
PRESENCE_OFFLINE = "offline"
PRESENCE_DEGRADED = "degraded"
PRESENCE_UNKNOWN = "unknown"
PRESENCE_STATES = frozenset(
    {PRESENCE_ONLINE, PRESENCE_OFFLINE, PRESENCE_DEGRADED, PRESENCE_UNKNOWN}
)

# Ordered by precedence. The lease-aware owner-scoped blackboard entry wins;
# Hub is the per-device authority when there is none; the Data authority proves
# inventory and ownership only, and must never turn a lifecycle status such as
# ``active`` into an online state.
PRESENCE_SOURCE_BLACKBOARD = "runtime_blackboard"
PRESENCE_SOURCE_HUB = "hub"
PRESENCE_SOURCE_NONE = "none"
PRESENCE_SOURCES = frozenset(
    {PRESENCE_SOURCE_BLACKBOARD, PRESENCE_SOURCE_HUB, PRESENCE_SOURCE_NONE}
)

# ── companions ─────────────────────────────────────────────────────────────
# Lifecycle, not presence. Nothing in this system publishes a companion
# heartbeat, and this contract deliberately has no field for one: a field left
# open for a signal nobody feeds is eventually read as though it were fed.
#
# Imported rather than spelled out. This projection is *of* Companions the
# Companion authority publishes, and the two sets had already diverged: this
# file said active/pending/suspended/removed while Data publishes
# active/retiring/archived/deleting. That is not a naming difference — an
# archived Companion had no representable value here, so a projection carrying a
# real roster would have had to drop the row or invent a state for it.
from eidolon_sdk.biz.contracts.companion import (  # noqa: E402
    COMPANION_LIFECYCLE_STATES as _COMPANION_LIFECYCLE_STATES,
)

COMPANION_LIFECYCLE_STATES = frozenset(_COMPANION_LIFECYCLE_STATES)

# A device's logical role comes from the companion it is bound to, never from
# its board kind.
ROLE_KINDS = frozenset({"guard", "persona", "unbound"})

# ── activities ─────────────────────────────────────────────────────────────
ACTIVITY_KINDS = frozenset(
    {
        "voice_turn",
        "guard_event",
        "device_command",
        "device_event",
        "background_job",
    }
)

HOP_NODE_TYPES = frozenset(
    {"device", "companion", "service", "memory", "tool", "provider"}
)
HOP_DIRECTIONS = frozenset({"in", "out", "internal"})

# The turn stage vocabulary, in request order. Controlled because three
# surfaces point at the same instant with it — the constellation's asset moon,
# the backplane's wavefront and the route strip. Adding a stage is compatible
# (a consumer that does not know it simply lights nothing); changing what an
# existing key means is not.
STAGE_KEYS: tuple[str, ...] = (
    "input",
    "speech",
    "duck",
    "eot",
    "commit",
    "memory_recall",
    "agent_turn",
    "brain",
    "response",
    "tools",
    "tts",
    "playback",
    "memory_write",
)

# ── services ───────────────────────────────────────────────────────────────
SERVICE_TIERS = frozenset({"service", "middleware", "external"})

# ── shared with the audit envelope (pinned equal by test) ──────────────────
OUTCOMES = frozenset({"success", "failure", "denied", "deferred"})
SEVERITIES = frozenset({"info", "warn", "error", "critical"})
PRIVACY_CLASSES = frozenset({"safe", "sensitive", "restricted"})

# ── event stream ───────────────────────────────────────────────────────────
# No ``mock``. Staged data exists only inside a client and must never be able
# to arrive claiming a Host said it.
EVENT_ORIGINS = frozenset({"live", "polling", "replay"})

# The cursor is the audit index's own total order. A client submits the last
# sequence it consumed and the server replays from after it; there is no
# "from now", because a phone that backgrounds cannot afford one.
CURSOR_FIELD = "ingest_seq"

# Sent when the submitted cursor can no longer be honoured — its row was pruned,
# or the database behind it changed (a new reset epoch). The client drops its
# cursor and re-reads a snapshot. It must never silently resume from now.
STREAM_RESET_EVENT = "stream.reset"
