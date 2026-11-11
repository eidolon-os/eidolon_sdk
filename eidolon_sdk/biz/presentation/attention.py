"""Session-scoped attention messages between a device and its Host.

A device that follows faces or turns toward speech reports which input owns
its gaze and whether a target is present. No coordinates, no identity: who is
present is Person's business, not these messages'.

Three messages, one topic each:

* ``AttentionState`` (device to Host): coarse state of the gaze layer.
* ``AttentionSpeaker`` (device to Host): which of the device's own
  session-local tracks spoke during one user speech segment.
* ``AttentionLock`` (Host to device): the reply to an adopted turn has started
  or ended; hold the gaze on the reported track, or let it go.

``track_id`` is numbered by the device and means nothing outside one session;
the Host only echoes it back. Neither speaker nor lock carries a direction,
coordinate, image, name or person id, and no clock value takes part in the
logic, because device and Host clocks are not synchronised.
"""

from typing import Literal, Self

from pydantic import Field, model_validator

from . import Contract, Identifier, Unit

TOPIC = "eidolon.attention.v1"
EVENT_NAME = "attention.state"

SPEAKER_TOPIC = "eidolon.attention.speaker.v1"
SPEAKER_EVENT_NAME = "attention.speaker"
LOCK_TOPIC = "eidolon.attention.lock.v1"

LOCK_MIN_LEASE_MS = 500
LOCK_MAX_LEASE_MS = 30000
# A hold is renewed whenever the reply speaks again, so its lease only bounds a
# lost release. A release keeps the target for the tail before normal gaze.
LOCK_HOLD_LEASE_MS = 30000
LOCK_RELEASE_LEASE_MS = 1500


class AttentionState(Contract):
    version: Literal[1] = 1
    session_id: Identifier
    policy_revision: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=1)
    mode: Literal["off", "idle", "delegate_face", "look_point", "suspended"]
    source: Literal["face_tracker", "sound_direction", "host_target"] | None = None
    target_present: bool = Field(strict=True)
    speaking_direction: bool = Field(strict=True)
    following: bool = Field(strict=True)
    ts_ms: int = Field(strict=True, ge=0)


# Who spoke during one user speech segment, as the device attributes it.
# ``facts_sequence`` is the ``sequence`` of the ``InteractionFacts`` packet whose
# ``user_speaking=true`` opened the segment. The Host uses it, not a clock, to
# tell a late report about an earlier segment from a current one. A segment may
# produce a provisional report (``final=false``) and then a final one; the Host
# keeps the latest it accepted. (Comments, not a docstring: a docstring would
# become the schema's description and editing it would change the manifest.)
class AttentionSpeaker(Contract):
    version: Literal[1] = 1
    session_id: Identifier
    policy_revision: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=1)
    facts_sequence: int = Field(strict=True, ge=1)
    final: bool = Field(strict=True)
    track_id: Identifier | None = None
    basis: Literal["face", "voice", "none"]
    confidence: Unit
    in_view: bool = Field(strict=True)

    @model_validator(mode="after")
    def check_attribution(self) -> Self:
        if self.track_id is None and self.basis != "none":
            raise ValueError("SPEAKER_TRACK_REQUIRED")
        return self


# The reply to an adopted turn is playing (``hold``) or has ended (``release``).
# ``lease_ms`` is a hard upper bound counted on the device's own monotonic clock
# from receipt. ``track_id=None`` means a reply without an accepted speaker
# report; the device then falls back to its own rule. ``turn_id`` is the Host's
# turn number, carried only so logs on both sides can be joined.
class AttentionLock(Contract):
    version: Literal[1] = 1
    session_id: Identifier
    policy_revision: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=1)
    phase: Literal["hold", "release"]
    turn_id: Identifier | None = None
    track_id: Identifier | None = None
    speaker_sequence: int | None = Field(default=None, strict=True, ge=1)
    lease_ms: int = Field(strict=True, ge=LOCK_MIN_LEASE_MS, le=LOCK_MAX_LEASE_MS)

    @model_validator(mode="after")
    def check_binding(self) -> Self:
        if self.track_id is not None and self.speaker_sequence is None:
            raise ValueError("LOCK_SPEAKER_SEQUENCE_REQUIRED")
        return self


def _manifest_event(name: str, model: type[Contract]) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return {"name": name, "data_schema": schema}


def manifest_event() -> dict:
    """The manifest ``events`` entry a device declares when it publishes this state."""
    return _manifest_event(EVENT_NAME, AttentionState)


def speaker_manifest_event() -> dict:
    """The manifest ``events`` entry a device declares when it reports speakers.

    The declaration makes what leaves the device auditable. It is not what
    turns the lock on: the Host sends ``AttentionLock`` only after it has
    accepted at least one ``AttentionSpeaker`` in the session.
    """
    return _manifest_event(SPEAKER_EVENT_NAME, AttentionSpeaker)
