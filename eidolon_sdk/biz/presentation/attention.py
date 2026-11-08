"""Session-scoped attention state from a device: coarse observations, never commands.

A device that follows faces or turns toward speech reports which input owns
its gaze and whether a target is present. No coordinates, no identity: who is
present is Person's business, not this message's.
"""

from typing import Literal
from pydantic import Field
from . import Contract, Identifier

TOPIC = "eidolon.attention.v1"
EVENT_NAME = "attention.state"


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


def manifest_event() -> dict:
    """The manifest ``events`` entry a device declares when it publishes this state."""
    schema = AttentionState.model_json_schema()
    schema.pop("title", None)
    return {"name": EVENT_NAME, "data_schema": schema}
