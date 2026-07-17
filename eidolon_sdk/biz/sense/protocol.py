"""Strict, privacy-preserving wire contracts for the sense.* perception plane.

sense.* facts are the desktop-companion "vision organ" outputs. Two origins,
one envelope:

* on-device (T0): ``sense.attention`` and ``sense.session`` derived locally
  from face-detection telemetry;
* host Vision Worker (T2): ``sense.fatigue`` and ``sense.event`` distilled from
  gated image bursts, attributed to the model that produced them.

They are **owner-scoped ambient** facts (D1 ADR): the observing device belongs
to the owner, and whichever companion is currently engaged consumes them — the
facts are NOT pinned to a companion. Envelope discipline mirrors ``guard.*``
(bounded scalar signals, enums, no raw media / embeddings / biometric identity,
``extra="forbid"`` so pixels never leak into the control plane), but the scope
key is ``owner_id`` + ``device_id`` and is decoupled from GuardBinding.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

SENSE_SCHEMA_VERSION = 1
SENSE_ATTENTION_TYPE = "sense.attention"
SENSE_SESSION_TYPE = "sense.session"
SENSE_FATIGUE_TYPE = "sense.fatigue"
SENSE_EVENT_TYPE = "sense.event"
_SIGNAL_KEY_RE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


def _validate_signal_keys(
    value: dict[str, float | int | bool],
) -> dict[str, float | int | bool]:
    for key in value:
        if _SIGNAL_KEY_RE.fullmatch(key) is None:
            raise ValueError("sense signal names must be lowercase dotted identifiers")
    return value


class _SenseMessage(BaseModel):
    """Common envelope for sense.* facts on the ``eidolon.control`` data topic.

    Owner-scoped (D1 ADR): the fact is attributed to an owner + the observing
    device, NOT to a companion — whichever companion is currently engaged
    consumes it. The ingress derives/validates the owner from the authenticated
    device identity. Raw frames, audio, biometric templates, embeddings and
    media URLs are intentionally absent; receivers reject unknown fields so
    those payloads cannot enter the plane.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    schema_v: Literal[SENSE_SCHEMA_VERSION] = SENSE_SCHEMA_VERSION
    owner_id: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=96)
    epoch: int = Field(ge=0)
    ts_ms: int = Field(ge=0)


class SenseAttention(_SenseMessage):
    """Owner attention state, derived on-device from face bbox stability (T0).

    ``state`` is a coarse label, never gaze coordinates. Low confidence must be
    represented as ``relaxed`` — never as a rejection of the owner.
    """

    type: Literal[SENSE_ATTENTION_TYPE] = SENSE_ATTENTION_TYPE
    state: Literal["focused", "relaxed", "away_from_screen"]
    signals: dict[str, float | int | bool] = Field(default_factory=dict, max_length=16)
    raw_retention: Literal["none"] = "none"

    @field_validator("signals")
    @classmethod
    def _signals_use_bounded_extension_keys(
        cls, value: dict[str, float | int | bool]
    ) -> dict[str, float | int | bool]:
        return _validate_signal_keys(value)


class SenseSession(_SenseMessage):
    """Focus-session summary aggregated on-device (T0); statistics only.

    ``started`` marks a session boundary and carries no metrics; ``ended``
    reports the aggregate duration and interruption count.
    """

    type: Literal[SENSE_SESSION_TYPE] = SENSE_SESSION_TYPE
    state: Literal["started", "ended"]
    duration_ms: int = Field(default=0, ge=0, le=86_400_000)
    interruptions: int = Field(default=0, ge=0, le=100_000)
    raw_retention: Literal["none"] = "none"

    @model_validator(mode="after")
    def _validate_session_shape(self) -> "SenseSession":
        if self.state == "started" and (self.duration_ms != 0 or self.interruptions != 0):
            raise ValueError("started session must have duration_ms=0 and interruptions=0")
        return self


class SenseFatigue(_SenseMessage):
    """Fatigue hint distilled by the host Vision Worker (T2).

    Model-attributed so a model swap is auditable without changing the
    contract. Carries only the hint kind and bounded scalar signals (e.g. the
    aspect-ratio counts that triggered it) — no landmarks, no image.
    """

    type: Literal[SENSE_FATIGUE_TYPE] = SENSE_FATIGUE_TYPE
    hint: Literal["yawn", "drowsy", "slump"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_id: str = Field(min_length=1, max_length=96)
    model_version: str = Field(min_length=1, max_length=64)
    signals: dict[str, float | int | bool] = Field(default_factory=dict, max_length=16)
    raw_retention: Literal["none"] = "none"

    @field_validator("signals")
    @classmethod
    def _signals_use_bounded_extension_keys(
        cls, value: dict[str, float | int | bool]
    ) -> dict[str, float | int | bool]:
        return _validate_signal_keys(value)


class SenseEvent(_SenseMessage):
    """Coarse scene event distilled by the host Vision Worker (T2).

    Reports a bounded object class only — never a person's identity. Used for
    away-from-desk watching ("a person / a cat appeared"), not recognition.
    """

    type: Literal[SENSE_EVENT_TYPE] = SENSE_EVENT_TYPE
    event: Literal["person", "cat", "dog", "package"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_id: str = Field(min_length=1, max_length=96)
    model_version: str = Field(min_length=1, max_length=64)
    raw_retention: Literal["none"] = "none"


SenseMessage = Annotated[
    SenseAttention | SenseSession | SenseFatigue | SenseEvent,
    Field(discriminator="type"),
]

_SENSE_MESSAGE_ADAPTER = TypeAdapter(SenseMessage)


def parse_sense_message(payload: object) -> SenseMessage:
    """Validate a full sense.* fact; unsupported schema versions fail."""
    return _SENSE_MESSAGE_ADAPTER.validate_python(payload)
