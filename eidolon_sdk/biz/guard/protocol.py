"""Strict, privacy-preserving wire contracts for the ATK Guard P0 plane."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

GUARD_SCHEMA_VERSION = 1
SILENT_PRESENCE_POLICY_ID = "silent_presence"
GUARD_RUNTIME_SCHEMA_VERSION = 1
GUARD_PRESENCE_CANDIDATE_TYPE = "guard.presence.candidate"
GUARD_PRESENCE_ABSENT_TYPE = "guard.presence.absent"


class GuardSilentPresenceConfig(BaseModel):
    """The complete, non-sensitive configuration for the P1 policy.

    The binding owns this configuration.  It controls how Hub maps facts to
    durable actions, never how an ATK device captures or retains media.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_v: Literal[GUARD_SCHEMA_VERSION] = GUARD_SCHEMA_VERSION
    candidate_enabled: bool = True
    verified_enabled: bool = True
    accepted_verdicts: tuple[Literal["present", "unknown"], ...] = Field(
        default=("present", "unknown"),
        min_length=1,
    )
    absence_enabled: bool = True

    @field_validator("accepted_verdicts", mode="before")
    @classmethod
    def _accepted_verdicts_accept_json_arrays(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("accepted_verdicts")
    @classmethod
    def _accepted_verdicts_must_be_unique(
        cls,
        value: tuple[Literal["present", "unknown"], ...],
    ) -> tuple[Literal["present", "unknown"], ...]:
        if len(set(value)) != len(value):
            raise ValueError("accepted_verdicts must not contain duplicates")
        return value


class GuardRuntimeConfig(BaseModel):
    """Versioned, non-sensitive parameters applied by an ATK Guard runtime.

    This is deliberately distinct from :class:`GuardSilentPresenceConfig`:
    it controls local sampling only, while Hub remains the sole policy
    decision-maker.  It contains neither owner identity nor media data.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_v: Literal[GUARD_RUNTIME_SCHEMA_VERSION] = GUARD_RUNTIME_SCHEMA_VERSION
    sample_interval_ms: int = Field(default=500, ge=200, le=60_000)
    preview_interval_ms: int = Field(default=1_000, ge=200, le=60_000)
    motion_threshold: int = Field(default=18, ge=0, le=255)
    motion_clear_threshold: int = Field(default=9, ge=0, le=255)
    candidate_debounce_ms: int = Field(default=1_000, ge=200, le=600_000)
    absence_timeout_ms: int = Field(default=180_000, ge=400, le=3_600_000)
    consecutive_capture_failures: int = Field(default=5, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_runtime_relations(self) -> "GuardRuntimeConfig":
        if self.preview_interval_ms < self.sample_interval_ms:
            raise ValueError("preview_interval_ms must be at least sample_interval_ms")
        if self.motion_clear_threshold > self.motion_threshold:
            raise ValueError("motion_clear_threshold must not exceed motion_threshold")
        if self.candidate_debounce_ms < self.sample_interval_ms:
            raise ValueError("candidate_debounce_ms must be at least sample_interval_ms")
        if self.absence_timeout_ms < self.sample_interval_ms * 2:
            raise ValueError("absence_timeout_ms must be at least twice sample_interval_ms")
        return self


class _GuardMessage(BaseModel):
    """Common envelope carried on the ``eidolon.control`` data topic.

    Raw frames, audio samples, biometric templates, embeddings, and media URLs
    are intentionally absent. Receivers reject unknown fields so those payloads
    cannot silently enter the P0 control plane.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_v: Literal[GUARD_SCHEMA_VERSION] = GUARD_SCHEMA_VERSION
    guard_companion_id: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=96)
    guard_epoch: int = Field(ge=0)
    ts_ms: int = Field(ge=0)


class GuardCameraFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    frame_hash: str | None = Field(default=None, min_length=8, max_length=128)
    motion_score: float | None = Field(default=None, ge=0)


class GuardPresenceCandidate(_GuardMessage):
    type: Literal[GUARD_PRESENCE_CANDIDATE_TYPE] = GUARD_PRESENCE_CANDIDATE_TYPE
    signals: dict[str, float | int | bool] = Field(default_factory=dict)
    camera: GuardCameraFact | None = None
    raw_retention: Literal["none"] = "none"
    debounce_ms: int = Field(default=0, ge=0, le=600_000)


class GuardPresenceVerified(_GuardMessage):
    type: Literal["guard.presence.verified"] = "guard.presence.verified"
    verifier: Literal["fixture", "channel"] = "fixture"
    verdict: Literal["present", "unknown", "rejected"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    raw_retention: Literal["none"] = "none"


class GuardPresenceAbsent(_GuardMessage):
    type: Literal[GUARD_PRESENCE_ABSENT_TYPE] = GUARD_PRESENCE_ABSENT_TYPE
    reason: Literal["timeout", "clear", "policy"]
    absent_for_ms: int = Field(ge=0)
    raw_retention: Literal["none"] = "none"


class GuardPolicyAction(_GuardMessage):
    type: Literal["guard.policy.action"] = "guard.policy.action"
    action_id: str = Field(min_length=1, max_length=96)
    policy_id: str = Field(min_length=1, max_length=64)
    action: Literal[
        "mission_control.annotate",
        "mission_control.clear",
        "body.presence.set",
        "body.look_at",
    ]
    subscriber: str = Field(default="mission_control_fixture", min_length=1, max_length=128)
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    raw_retention: Literal["none"] = "none"


class GuardPolicyActionAck(_GuardMessage):
    type: Literal["guard.policy.action_ack"] = "guard.policy.action_ack"
    action_id: str = Field(min_length=1, max_length=96)
    subscriber: str = Field(default="mission_control_fixture", min_length=1, max_length=128)
    status: Literal["accepted", "completed", "failed"]
    message: str = Field(default="", max_length=256)


GuardMessage = Annotated[
    GuardPresenceCandidate
    | GuardPresenceVerified
    | GuardPresenceAbsent
    | GuardPolicyAction
    | GuardPolicyActionAck,
    Field(discriminator="type"),
]

_GUARD_MESSAGE_ADAPTER = TypeAdapter(GuardMessage)


def parse_guard_message(payload: object) -> GuardMessage:
    """Validate a full P0 guard message; unsupported schema versions fail."""
    return _GUARD_MESSAGE_ADAPTER.validate_python(payload)


def parse_guard_policy_config(
    policy_id: str,
    payload: object | None,
) -> GuardSilentPresenceConfig:
    """Validate the active policy's configuration without widening its scope.

    P1 intentionally supports one policy type.  Future policy kinds must add a
    new explicit contract here instead of turning ``config_json`` into an
    unbounded pass-through document.
    """
    if policy_id != SILENT_PRESENCE_POLICY_ID:
        raise ValueError(f"unsupported guard policy: {policy_id!r}")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("guard policy config must be an object")
    return GuardSilentPresenceConfig.model_validate(payload)


def normalize_guard_policy_config(policy_id: str, payload: object | None) -> dict[str, object]:
    """Return the canonical persisted JSON shape for a policy configuration."""
    return parse_guard_policy_config(policy_id, payload).model_dump(mode="json")


def parse_guard_runtime_config(payload: object | None) -> GuardRuntimeConfig:
    """Validate a Guard device runtime configuration object."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("guard runtime config must be an object")
    return GuardRuntimeConfig.model_validate(payload)


def normalize_guard_runtime_config(payload: object | None) -> dict[str, object]:
    """Return the canonical persisted JSON shape for runtime parameters."""
    return parse_guard_runtime_config(payload).model_dump(mode="json")
