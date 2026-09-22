"""Versioned, transport-neutral companion presentation contracts.

Visual curves belong to the device's shared renderer, not this package. IDs,
limits, output selection and receipt semantics are shared by every consumer.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

FACE_PROFILE = "eidolon.face.v1"
FACE_CATALOG = "face-core-1"
MAX_PLAN_BYTES = 2048
MAX_STEPS = 8
MAX_DURATION_MS = 10000

Intent = Literal[
    "acknowledge",
    "confirm",
    "consider",
    "clarify",
    "comfort",
    "celebrate",
    "decline",
    "notify",
    "none",
]
Gesture = Literal[
    "attend", "affirm", "ponder", "question", "soften", "delight", "hesitate", "attention"
]
Identifier = Annotated[str, Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_.:-]+$")]
Unit = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Millis = Annotated[int, Field(strict=True, ge=0, le=MAX_DURATION_MS)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, value: Any) -> Any:
        if isinstance(value, dict) and "schema_version" in value:
            if type(value["schema_version"]) is not int:
                raise ValueError("SCHEMA_VERSION_MUST_BE_INTEGER")
        return value


class OutputSelection(Contract):
    speech: bool = Field(default=False, strict=True)
    dialogue_text: bool = Field(default=False, strict=True)
    expression: bool = Field(default=False, strict=True)
    audio_cue: bool = Field(default=False, strict=True)
    motion: bool = Field(default=False, strict=True)

    def restrict(self, other: OutputSelection) -> OutputSelection:
        return OutputSelection(
            **{key: getattr(self, key) and getattr(other, key) for key in type(self).model_fields}
        )

    @property
    def can_respond(self) -> bool:
        return self.speech or self.dialogue_text or self.expression or self.motion


class InputSelection(Contract):
    """Owner permission to send microphone audio, independent of response outputs."""

    microphone: bool = Field(default=False, strict=True)


def manifest_inputs(manifest: dict[str, Any]) -> InputSelection:
    return InputSelection(microphone=any(
        isinstance(entry, dict) and entry.get("kind") == "audio"
        and entry.get("direction") in {"publish", "bidirectional"}
        for entry in manifest.get("media", ())
    ))


class DeviceOutputPolicy(Contract):
    """Device interaction permissions sharing one atomic revision.

    The wire name predates input controls. Inputs remain a separate selection;
    they are never response outputs or part of presentation negotiation.
    None preserves the historical microphone behavior for existing policies.
    """
    schema_version: Literal[1] = 1
    revision: Annotated[int, Field(strict=True, ge=1, le=4294967295)]
    allowed: OutputSelection
    inputs: InputSelection | None = None


class SessionOutputPlan(Contract):
    schema_version: Literal[1] = 1
    session_id: Identifier
    policy_revision: Annotated[int, Field(strict=True, ge=1, le=4294967295)]
    outputs: OutputSelection
    inputs: InputSelection = Field(default_factory=lambda: InputSelection(microphone=True))
    expression_profile: Literal["eidolon.face.v1"] | None = None

    @model_validator(mode="after")
    def check_outputs(self) -> Self:
        if self.outputs.expression != (self.expression_profile is not None):
            raise ValueError("EXPRESSION_PROFILE_REQUIRED")
        return self


class PresentationCandidate(Contract):
    intent: Intent
    stance: Literal["neutral", "warm", "calm", "playful"] = "neutral"
    intensity: Unit = 0.3
    pace: Literal["gentle", "normal", "brisk"] = "normal"
    outcome_ref: Identifier | None = None


class AssistantResponseCandidate(Contract):
    schema_version: Literal[1] = 1
    public_text: Annotated[str, Field(max_length=8192)] | None = None
    presentation: PresentationCandidate = Field(default_factory=lambda: PresentationCandidate(intent="none"))


class ResponseIntent(PresentationCandidate):
    """Only emitted after Agent validates outcome_ref against actual results."""

    schema_version: Literal[1] = 1
    response_id: Identifier
    turn_id: Identifier
    session_id: Identifier


class ExpressionStep(Contract):
    at_ms: Millis = 0
    gesture: Gesture
    variant: Literal["default", "subtle"] = "default"
    intensity: Unit = 0.3
    duration_ms: Annotated[int, Field(strict=True, ge=150, le=MAX_DURATION_MS)]


class ExpressionPlan(Contract):
    schema_version: Literal[1] = 1
    presentation_id: Identifier
    response_id: Identifier
    profile: Literal["eidolon.face.v1"] = FACE_PROFILE
    catalog_revision: Literal["face-core-1"] = FACE_CATALOG
    max_duration_ms: Annotated[int, Field(strict=True, ge=150, le=MAX_DURATION_MS)]
    steps: Annotated[tuple[ExpressionStep, ...], Field(min_length=1, max_length=MAX_STEPS)]
    on_finish: Literal["resume_current_base"] = "resume_current_base"

    @model_validator(mode="after")
    def check_timeline(self) -> Self:
        end = 0
        for step in self.steps:
            if step.at_ms < end:
                raise ValueError("OVERLAPPING_OR_UNSORTED_STEPS")
            end = step.at_ms + step.duration_ms
        if end > self.max_duration_ms:
            raise ValueError("PLAN_DURATION_EXCEEDED")
        return self

    @classmethod
    def from_wire(cls, payload: str | bytes) -> Self:
        if len(payload.encode("utf-8") if isinstance(payload, str) else payload) > MAX_PLAN_BYTES:
            raise ValueError("PLAN_TOO_LARGE")

        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("DUPLICATE_JSON_FIELD")
                result[key] = value
            return result

        return cls.model_validate(json.loads(payload, object_pairs_hook=unique))


class PresentationReceipt(Contract):
    schema_version: Literal[1] = 1
    presentation_id: Identifier
    response_id: Identifier
    status: Literal["accepted", "started", "completed", "cancelled", "rejected", "failed"]
    sequence: Annotated[int, Field(strict=True, ge=1, le=4294967295)]
    reason: Annotated[str, Field(max_length=96)] = ""
    elapsed_ms: Millis = 0


class PlayExpression(Contract):
    """Payload of expression.play on the existing authenticated control channel."""

    session_id: Identifier
    policy_revision: Annotated[int, Field(strict=True, ge=1, le=4294967295)]
    plan: ExpressionPlan


class CancelExpression(Contract):
    session_id: Identifier
    policy_revision: Annotated[int, Field(strict=True, ge=1, le=4294967295)]
    presentation_id: Identifier


EXPRESSION_PLAY_OP = "expression.play"
EXPRESSION_CANCEL_OP = "expression.cancel"
