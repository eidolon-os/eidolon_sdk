"""Canonical PH2 Admission bindings with nominal identities and closed states."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .lifecycle import (
    ActorRef,
    BusinessOwnerId,
    DeviceRef,
    ManifestRef,
    OwnerDomainId,
    _aware_datetime,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EnrollmentProposalState(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED_AWAITING_HANDOFF = "approved_awaiting_handoff"
    GRANT_DELIVERED = "grant_delivered"
    GRANT_ACKNOWLEDGED = "grant_acknowledged"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELED = "canceled"
    CLAIM_REVOKED = "claim_revoked"


class ClaimState(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class ControllerActorRef(ActorRef):
    principal_type: Literal["controller"] = "controller"
    owner_domain_id: OwnerDomainId


class EnrollmentProposal(_Model):
    enrollment_id: str = Field(min_length=3, max_length=128)
    proposal_revision: int = Field(ge=1)
    state: EnrollmentProposalState
    device_instance_candidate_id: str = Field(min_length=3, max_length=128)
    requested_owner_domain_id: OwnerDomainId
    hardware_evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    manifest_ref: ManifestRef
    handoff_key_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _deadline(self) -> EnrollmentProposal:
        if self.expires_at <= self.created_at:
            raise ValueError("proposal expires_at must follow created_at")
        return self


class ApprovalDecision(_Model):
    decision_id: str = Field(min_length=3, max_length=128)
    enrollment_id: str = Field(min_length=3, max_length=128)
    decision: Literal["approve", "reject"]
    actor: ControllerActorRef
    target_owner_domain_id: OwnerDomainId
    target_business_owner_id: BusinessOwnerId
    reviewed_manifest_ref: ManifestRef
    expected_proposal_revision: int = Field(ge=1)
    decided_at: datetime

    @field_validator("decided_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _owner_scope(self) -> ApprovalDecision:
        if self.actor.owner_domain_id != self.target_owner_domain_id:
            raise ValueError("Decision actor and target Owner Domain do not match")
        return self


class ClaimGrant(_Model):
    grant_id: str = Field(min_length=3, max_length=128)
    enrollment_id: str = Field(min_length=3, max_length=128)
    device_ref: DeviceRef
    manifest_ref: ManifestRef
    approval_decision_id: str = Field(min_length=3, max_length=128)
    handoff_key_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    operational_key_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    issued_at: datetime
    expires_at: datetime

    @field_validator("issued_at", "expires_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class GrantAck(_Model):
    enrollment_id: str = Field(min_length=3, max_length=128)
    grant_id: str = Field(min_length=3, max_length=128)
    device_ref: DeviceRef
    acknowledged_at: datetime

    @field_validator("acknowledged_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class ClaimRecord(_Model):
    device_ref: DeviceRef
    business_owner_id: BusinessOwnerId
    manifest_ref: ManifestRef
    state: ClaimState
    revision: int = Field(ge=1)
    updated_at: datetime

    @field_validator("updated_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)

