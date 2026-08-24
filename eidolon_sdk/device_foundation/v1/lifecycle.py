"""Canonical Python bindings for exact-generation device removal."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

import rfc8785
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _wire_datetime(value: object) -> object:
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _aware_datetime(value: object) -> datetime:
    value = _wire_datetime(value)
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return value.astimezone(UTC)


_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"


class OwnerDomainId(RootModel[str]):
    """Nominal Owner Sovereign Domain identifier; never a tenant/account id."""

    model_config = ConfigDict(frozen=True, strict=True)

    @field_validator("root")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not 3 <= len(value) <= 128 or not value.startswith("owner-"):
            raise ValueError("OwnerDomainId must use the owner- namespace")
        return value

    def __str__(self) -> str:
        return self.root


class BusinessOwnerId(RootModel[str]):
    """Nominal business Owner/tenant identifier; never an Owner Domain id."""

    model_config = ConfigDict(frozen=True, strict=True)

    @field_validator("root")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not 3 <= len(value) <= 128 or not value.startswith("owner_"):
            raise ValueError("BusinessOwnerId must use the owner_ namespace")
        return value

    def __str__(self) -> str:
        return self.root


class ManifestRef(_Model):
    manifest_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    revision: int = Field(ge=1)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class DeviceRef(_Model):
    device_instance_id: str = Field(
        min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    owner_domain_id: OwnerDomainId
    owner_domain_generation: int = Field(ge=1)
    claim_generation: int = Field(ge=1)
    trust_epoch: int = Field(ge=1)


class CommandEnvelope(_Model):
    contract: Literal["eidolon.device-foundation.command"] = "eidolon.device-foundation.command"
    contract_version: Literal["1.0"] = "1.0"
    command_type: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    correlation_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    causation_id: str | None = Field(default=None, min_length=3, max_length=128)
    issued_at: datetime
    deadline: datetime | None
    payload: dict[str, object]
    extensions: dict[str, object]

    @field_validator("issued_at", "deadline", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime | None:
        return None if value is None else _aware_datetime(value)


class CommandResult(_Model):
    command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    outcome: Literal["committed", "replayed", "accepted"]
    resource_ref: dict[str, object]
    resource_revision: int | None = Field(default=None, ge=0)
    occurred_at: datetime
    extensions: dict[str, object]

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class DeviceProblem(_Model):
    code: Literal[
        "INVALID_ARGUMENT", "CONTRACT_UNSUPPORTED", "UNAUTHENTICATED", "FORBIDDEN",
        "NOT_FOUND", "IDEMPOTENCY_CONFLICT", "REVISION_CONFLICT", "GENERATION_CONFLICT",
        "CLAIM_REVOKED", "TRUST_EPOCH_STALE", "OWNER_DOMAIN_MISMATCH",
        "BUSINESS_OWNER_MISMATCH", "DECISION_REQUIRED", "HANDOFF_PROOF_INVALID",
        "GRANT_EXPIRED", "PROPOSAL_TERMINAL", "PROPOSAL_EXPIRED", "OPERATION_EXPIRED",
        "RATE_LIMITED", "AUTHORITY_UNAVAILABLE", "DELIVERY_UNAVAILABLE", "INTERNAL",
    ]
    category: Literal["invalid", "auth", "forbidden", "missing", "conflict", "expired", "unavailable", "internal"]
    retryable: bool
    authority: Literal["admission", "device-control", "body-mesh", "companion", "delivery"]
    command_id: str | None = None
    resource_ref: dict[str, object] | None
    current_revision: int | None = Field(default=None, ge=0)
    current_generation: int | None = Field(default=None, ge=0)
    retry_after_ms: int | None = Field(default=None, ge=1)
    detail: str = Field(max_length=1024)
    incident_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)

    @model_validator(mode="after")
    def _retry(self) -> DeviceProblem:
        if not self.retryable and self.retry_after_ms is not None:
            raise ValueError("non-retryable problem cannot carry retry_after_ms")
        if self.code == "RATE_LIMITED" and (not self.retryable or self.retry_after_ms is None):
            raise ValueError("RATE_LIMITED must be retryable with retry_after_ms")
        return self


class ActorRef(_Model):
    principal_id: str = Field(
        min_length=3, max_length=128, pattern=_IDENTIFIER
    )
    principal_type: Literal["controller", "device", "service", "operator"]
    owner_domain_id: OwnerDomainId | None = None
    granted_scopes: tuple[str, ...] = Field(min_length=1)
    authentication_strength: Literal[
        "software", "hardware-backed", "physical-presence"
    ]

    @field_validator("granted_scopes", mode="before")
    @classmethod
    def _unique_scopes(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            value = tuple(value)
        if not isinstance(value, tuple):
            raise ValueError("granted_scopes must be an array")
        if len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("granted_scopes must be unique and non-empty")
        return value


class OwnerAuthorizationContext(_Model):
    workload_principal_id: str = Field(
        min_length=3, max_length=128, pattern=_IDENTIFIER
    )
    actor: ActorRef
    authorized_owner_domain_id: OwnerDomainId
    audience: Literal["eidolon-admission"] = "eidolon-admission"
    scopes: tuple[Literal["device.read", "device.claim.revoke"], ...] = Field(
        min_length=1
    )
    intent_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    target_device_ref: DeviceRef
    issued_at: datetime
    expires_at: datetime

    @field_validator("scopes", mode="before")
    @classmethod
    def _scope_array(cls, value: object) -> object:
        value = tuple(value) if isinstance(value, list) else value
        if isinstance(value, tuple) and len(value) != len(set(value)):
            raise ValueError("authorization scopes must be unique")
        return value

    @field_validator("issued_at", "expires_at", mode="before")
    @classmethod
    def _aware(cls, value: object) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _coherent(self) -> OwnerAuthorizationContext:
        if self.expires_at <= self.issued_at:
            raise ValueError("authorization expires_at must follow issued_at")
        if self.authorized_owner_domain_id != self.target_device_ref.owner_domain_id:
            raise ValueError("authorization Owner and target DeviceRef do not match")
        if self.actor.owner_domain_id not in {None, self.authorized_owner_domain_id}:
            raise ValueError("actor Owner and authorized Owner do not match")
        if "device.claim.revoke" not in self.scopes:
            raise ValueError("removal authorization requires device.claim.revoke")
        if not set(self.scopes).issubset(self.actor.granted_scopes):
            raise ValueError("authorization scopes exceed the ActorRef grant")
        return self


class RemovalIntent(_Model):
    intent_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    ingress_request_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    device_ref: DeviceRef
    actor: ActorRef
    reason: str = Field(min_length=1, max_length=256)
    claim_command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    state: Literal["accepted", "claim-revoked", "converged", "blocked"]
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _timestamps(cls, value: object) -> object:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _coherent(self) -> RemovalIntent:
        if self.updated_at < self.created_at:
            raise ValueError("RemovalIntent updated_at precedes created_at")
        if self.actor.owner_domain_id not in {None, self.device_ref.owner_domain_id}:
            raise ValueError("RemovalIntent actor Owner and DeviceRef do not match")
        return self


class RevokeClaim(_Model):
    operation: Literal["device.claim-revocation"] = "device.claim-revocation"
    command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    correlation_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    device_ref: DeviceRef
    reason: str = Field(min_length=1, max_length=256)


class RevokeClaimResult(_Model):
    operation: Literal["device.claim-revocation-result"] = (
        "device.claim-revocation-result"
    )
    command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    outcome: Literal["committed", "replayed"]
    device_ref: DeviceRef
    aggregate_revision: int = Field(ge=1)
    occurred_at: datetime
    event_id: str | None = Field(default=None, min_length=3, max_length=128)
    lifecycle_state: Literal["revoked"] = "revoked"

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _occurred_at(cls, value: object) -> object:
        return _aware_datetime(value)


def revoke_claim_fingerprint(command: RevokeClaim) -> str:
    """Fingerprint one semantic revoke mutation, excluding retry/audit metadata."""

    document = {
        "command_type": "device.claim.revoke",
        "owner_domain_id": str(command.device_ref.owner_domain_id),
        "payload": {
            "device_ref": command.device_ref.model_dump(mode="json"),
            "reason": command.reason,
        },
    }
    return "sha256:" + hashlib.sha256(rfc8785.dumps(document)).hexdigest()
