"""Interaction interpretation v1: what an input asks for, never a grant to do it.

Sibling of ``biz.participation`` (who speaks next). This one answers what a
single utterance wants done and to which of the candidates the caller offered.
Any implementation (rules, a small model, an LLM classifier) must fit it, and
the caller re-checks every proposal against current state before acting.

An implementation sees only the request: it does not read device directories,
hold device tokens, or execute anything. Ambiguity is stated, never resolved by
guessing an identifier.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

SCHEMA_VERSION = 1

Domain = Literal["smarthome"]
Intent = Literal["control", "query", "unrelated"]
TargetStatus = Literal["resolved", "ambiguous", "none"]

Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r"\S")]
Name = Annotated[str, Field(strict=True, min_length=1, max_length=64, pattern=r"\S")]

# Transport errors an adapter raises instead of returning a result.
ERROR_INVALID_REQUEST = "INVALID_REQUEST"
ERROR_UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
ERROR_CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"
ERROR_TIMEOUT = "TIMEOUT"
ERROR_UNAVAILABLE = "UNAVAILABLE"
ERROR_IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
ERROR_INVALID_PROPOSAL = "INVALID_PROPOSAL"
RETRYABLE_ERRORS = frozenset({ERROR_TIMEOUT, ERROR_UNAVAILABLE})
ERROR_CODES = frozenset(
    {
        ERROR_INVALID_REQUEST,
        ERROR_UNSUPPORTED_VERSION,
        ERROR_CONTEXT_TOO_LARGE,
        ERROR_TIMEOUT,
        ERROR_UNAVAILABLE,
        ERROR_IDEMPOTENCY_CONFLICT,
        ERROR_INVALID_PROPOSAL,
    }
)


class InterpretationError(Exception):
    """An adapter could not produce a result. Never read this as "unrelated"."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown interpretation error code {code!r}")
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.retryable = code in RETRYABLE_ERRORS


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Candidate(Contract):
    """Something the utterance may refer to. ``kind`` is a device type or "scene"."""

    ref: Identifier
    name: Name
    aliases: Annotated[tuple[Name, ...], Field(max_length=8)] = ()
    kind: Identifier
    area_id: Identifier | None = None


class Area(Contract):
    area_id: Identifier
    name: Name


class Origin(Contract):
    """Where the utterance was heard. ``area_id`` is the default room, when known."""

    device_ref: Identifier | None = None
    area_id: Identifier | None = None


class InterpretationRequest(Contract):
    schema_version: Literal[1] = SCHEMA_VERSION
    interpretation_id: Identifier
    domain: Domain
    utterance: Annotated[str, Field(strict=True, min_length=1, max_length=512)]
    origin: Origin = Field(default_factory=Origin)
    candidates: Annotated[tuple[Candidate, ...], Field(max_length=256)]
    areas: Annotated[tuple[Area, ...], Field(max_length=64)] = ()
    allowed_intents: Annotated[tuple[Intent, ...], Field(min_length=1, max_length=3)] = (
        "control",
        "query",
        "unrelated",
    )
    timeout_ms: Annotated[int, Field(strict=True, ge=1, le=10000)]
    # Caller-owned, bounded conversation facts; never an execution grant.
    context: dict[str, JsonValue] | None = None

    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, value):
        if isinstance(value, dict) and "schema_version" in value:
            if type(value["schema_version"]) is not int:
                raise ValueError("SCHEMA_VERSION_MUST_BE_INTEGER")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        import json
        if self.context is not None and len(json.dumps(self.context, ensure_ascii=False).encode()) > 16384:
            raise ValueError("CONTEXT_TOO_LARGE")
        refs = [c.ref for c in self.candidates]
        if len(set(refs)) != len(refs):
            raise ValueError("DUPLICATE_CANDIDATE")
        area_ids = {a.area_id for a in self.areas}
        if len(area_ids) != len(self.areas):
            raise ValueError("DUPLICATE_AREA")
        for candidate in self.candidates:
            if candidate.area_id is not None and candidate.area_id not in area_ids:
                raise ValueError("CANDIDATE_AREA_UNKNOWN")
        if self.origin.area_id is not None and self.origin.area_id not in area_ids:
            raise ValueError("ORIGIN_AREA_UNKNOWN")
        if len(set(self.allowed_intents)) != len(self.allowed_intents):
            raise ValueError("DUPLICATE_ALLOWED_INTENT")
        return self


class Slot(Contract):
    """A value lifted from the utterance, e.g. celsius=24 from "调到24度"."""

    name: Identifier
    value: bool | int | float | str
    unit: Annotated[str | None, Field(max_length=16)] = None
    raw_span: Annotated[str | None, Field(max_length=64)] = None


class Action(Contract):
    """Domain vocabulary; for smarthome, a trait and command from biz.smarthome."""

    trait: Identifier
    command: Identifier
    slots: Annotated[tuple[Slot, ...], Field(max_length=8)] = ()


class Proposal(Contract):
    intent: Intent
    target_status: TargetStatus
    targets: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()
    action: Action | None = None
    # What the utterance named when nothing matched ("投影仪"), so the caller can
    # say which thing the home lacks. Only with target_status "none".
    mention: Annotated[str | None, Field(max_length=32)] = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("DUPLICATE_TARGET")
        count = len(self.targets)
        if self.intent == "unrelated":
            if self.target_status != "none" or count or self.action is not None or self.mention:
                raise ValueError("UNRELATED_CARRIES_TARGET")
            return self
        if self.target_status == "resolved" and count == 0:
            raise ValueError("RESOLVED_WITHOUT_TARGET")
        if self.target_status == "ambiguous" and count < 2:
            raise ValueError("AMBIGUOUS_NEEDS_CANDIDATES")
        if self.target_status == "none" and count:
            raise ValueError("NONE_CARRIES_TARGET")
        if self.mention is not None and self.target_status != "none":
            raise ValueError("MENTION_ONLY_WHEN_NONE")
        if self.intent == "control" and self.action is None:
            raise ValueError("CONTROL_WITHOUT_ACTION")
        return self


class InterpretationResult(Contract):
    schema_version: Literal[1] = SCHEMA_VERSION
    interpretation_id: Identifier
    status: Literal["decided", "abstained"]
    proposal: Proposal | None = None
    policy_version: Identifier
    model_version: Identifier
    # Bounded, documented diagnostics only (e.g. a calibrated probability).
    diagnostics: Annotated[dict[str, bool | int | float | str], Field(max_length=16)] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if (self.status == "decided") != (self.proposal is not None):
            raise ValueError("PROPOSAL_DOES_NOT_MATCH_STATUS")
        return self


def validate_proposal(request: InterpretationRequest, result: InterpretationResult) -> None:
    """Reject a stale or out-of-bounds proposal. This does not authorize acting on it.

    Callers must still check the targets against current authority state and
    validate the action with the domain's own vocabulary before executing.
    """
    if result.interpretation_id != request.interpretation_id:
        raise ValueError("INTERPRETATION_ID_MISMATCH")
    proposal = result.proposal
    if proposal is None:
        return
    if proposal.intent not in request.allowed_intents:
        raise ValueError("INTENT_NOT_ALLOWED")
    refs = {c.ref for c in request.candidates}
    if not set(proposal.targets) <= refs:
        raise ValueError("TARGET_OUTSIDE_CANDIDATES")


__all__ = [
    "Action",
    "Area",
    "Candidate",
    "ERROR_CODES",
    "InterpretationError",
    "InterpretationRequest",
    "InterpretationResult",
    "Origin",
    "Proposal",
    "RETRYABLE_ERRORS",
    "SCHEMA_VERSION",
    "Slot",
    "validate_proposal",
]
