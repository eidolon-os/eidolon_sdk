"""Canonical PH2 Admission bindings with nominal identities and closed states."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .lifecycle import (
    WireEnum,
    ActorRef,
    BusinessOwnerId,
    DeviceRef,
    ManifestRef,
    OwnerDomainId,
    _aware_datetime,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EnrollmentProposalState(WireEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED_AWAITING_HANDOFF = "approved_awaiting_handoff"
    GRANT_DELIVERED = "grant_delivered"
    GRANT_ACKNOWLEDGED = "grant_acknowledged"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELED = "canceled"
    CLAIM_REVOKED = "claim_revoked"


class ClaimState(WireEnum):
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


class HardwareIdentityEvidence(_Model):
    scheme: Literal["manufacturer-p256", "dev-self-signed-p256"]
    evidence: str = Field(min_length=16, max_length=65536)
    evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CommissioningProof(_Model):
    scheme: Literal["protocomm-security2-srp6a-aes256gcm"] = "protocomm-security2-srp6a-aes256gcm"
    proof: str = Field(min_length=16, max_length=4096)
    nonce: str = Field(min_length=16, max_length=256)


class ManifestDocument(_Model):
    manifest_id: str = Field(min_length=3, max_length=128)
    revision: int = Field(ge=1)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    document: dict[str, Any]


class HandoffPublicKey(_Model):
    scheme: Literal["DHKEM-P256-HKDF-SHA256"] = "DHKEM-P256-HKDF-SHA256"
    public_key: str = Field(pattern=r"^p256-spki:[A-Za-z0-9_-]+$")


class OperationalPublicKey(_Model):
    scheme: Literal["ES256-P256"] = "ES256-P256"
    public_key: str = Field(pattern=r"^p256-spki:[A-Za-z0-9_-]+$")


class CreateEnrollment(_Model):
    profile_id: Literal["eidolon-trust-p256-hpke-v1"] = "eidolon-trust-p256-hpke-v1"
    device_instance_candidate_id: str = Field(min_length=3, max_length=128)
    requested_owner_domain_id: OwnerDomainId
    hardware_identity_evidence: HardwareIdentityEvidence
    commissioning_proof: CommissioningProof
    manifest: ManifestDocument
    handoff_key: HandoffPublicKey
    operational_key: OperationalPublicKey


class CreateEnrollmentResult(_Model):
    enrollment_id: str = Field(min_length=3, max_length=128)
    proposal_revision: int = Field(ge=1)
    state: Literal["pending_review"] = "pending_review"
    expires_at: datetime
    reviewed_manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    collection_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{22,128}$")

    @field_validator("expires_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class CancelEnrollment(_Model):
    enrollment_id: str = Field(min_length=3, max_length=128)
    reason: str = Field(min_length=1, max_length=256)


class CancelEnrollmentResult(_Model):
    enrollment_id: str = Field(min_length=3, max_length=128)
    proposal_state: Literal["canceled"] = "canceled"
    canceled_at: datetime

    @field_validator("canceled_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class DecideEnrollment(_Model):
    enrollment_id: str = Field(min_length=3, max_length=128)
    expected_proposal_revision: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    target_owner_domain_id: OwnerDomainId
    target_business_owner_id: BusinessOwnerId
    target_space_id: str | None = Field(default=None, min_length=3, max_length=128)
    reviewed_manifest_ref: ManifestRef
    initial_assignment_intent: dict[str, Any] | None = None
    initial_capability_policy_refs: tuple[str, ...] = ()

    @field_validator("initial_capability_policy_refs", mode="before")
    @classmethod
    def _policies(cls, value: object) -> object:
        value = tuple(value) if isinstance(value, list) else value
        if isinstance(value, tuple) and len(value) != len(set(value)):
            raise ValueError("capability policy refs must be unique")
        return value


class DecideEnrollmentResult(_Model):
    decision_id: str = Field(min_length=3, max_length=128)
    decision: Literal["approve", "reject"]
    decided_by: ControllerActorRef
    decided_at: datetime
    proposal_revision: int = Field(ge=1)

    @field_validator("decided_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class CollectClaimGrant(_Model):
    enrollment_id: str = Field(min_length=3, max_length=128)
    proposal_revision: int = Field(ge=1)
    collection_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{22,128}$")
    handoff_key_proof: str = Field(min_length=16, max_length=4096)


class ClaimGrantAAD(_Model):
    contract: Literal["eidolon.device-foundation.claim-grant-aad"] = (
        "eidolon.device-foundation.claim-grant-aad"
    )
    profile_id: Literal["eidolon-trust-p256-hpke-v1"] = "eidolon-trust-p256-hpke-v1"
    enrollment_id: str = Field(min_length=3, max_length=128)
    proposal_revision: int = Field(ge=1)
    device_instance_id: str = Field(min_length=3, max_length=128)
    hardware_evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    manifest_ref: ManifestRef
    owner_domain_id: OwnerDomainId
    owner_domain_generation: int = Field(ge=1)
    claim_generation: int = Field(ge=1)
    trust_epoch: int = Field(ge=1)
    grant_id: str = Field(min_length=3, max_length=128)

    def assert_matches_grant(self, grant: ClaimGrant) -> None:
        expected = (
            grant.enrollment_id,
            grant.device_ref.device_instance_id,
            grant.manifest_ref,
            grant.device_ref.owner_domain_id,
            grant.device_ref.owner_domain_generation,
            grant.device_ref.claim_generation,
            grant.device_ref.trust_epoch,
            grant.grant_id,
        )
        actual = (
            self.enrollment_id,
            self.device_instance_id,
            self.manifest_ref,
            self.owner_domain_id,
            self.owner_domain_generation,
            self.claim_generation,
            self.trust_epoch,
            self.grant_id,
        )
        if actual != expected:
            raise ValueError("ClaimGrant plaintext does not match the authenticated envelope AAD")


class ClaimGrantWireEnvelope(_Model):
    contract: Literal["eidolon.device-foundation.claim-grant-envelope"] = (
        "eidolon.device-foundation.claim-grant-envelope"
    )
    profile_id: Literal["eidolon-trust-p256-hpke-v1"] = "eidolon-trust-p256-hpke-v1"
    kem: Literal["DHKEM-P256-HKDF-SHA256"] = "DHKEM-P256-HKDF-SHA256"
    kdf: Literal["HKDF-SHA256"] = "HKDF-SHA256"
    aead: Literal["AES-128-GCM"] = "AES-128-GCM"
    recipient_handoff_key_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    encapsulated_key: str = Field(pattern=r"^[A-Za-z0-9_-]{87}$")
    ciphertext: str = Field(min_length=22, max_length=131072, pattern=r"^[A-Za-z0-9_-]+$")
    aad: ClaimGrantAAD


class CollectClaimGrantResult(_Model):
    grant_id: str = Field(min_length=3, max_length=128)
    wire_envelope: ClaimGrantWireEnvelope
    expires_at: datetime
    approval_decision_id: str = Field(min_length=3, max_length=128)

    @field_validator("expires_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _grant_id_matches(self) -> CollectClaimGrantResult:
        if self.wire_envelope.aad.grant_id != self.grant_id:
            raise ValueError("collect result grant_id does not match envelope AAD")
        return self


class AckClaimGrant(_Model):
    enrollment_id: str = Field(min_length=3, max_length=128)
    grant_id: str = Field(min_length=3, max_length=128)
    operational_key_proof: str = Field(min_length=16, max_length=4096)
    stored_claim_generation: int = Field(ge=1)
    stored_trust_epoch: int = Field(ge=1)


class AckClaimGrantResult(_Model):
    device_ref: DeviceRef
    claim_state: Literal["active"] = "active"


class GrantDeliveryRecord(_Model):
    grant_id: str = Field(min_length=3, max_length=128)
    approval_decision_id: str = Field(min_length=3, max_length=128)
    state: Literal["delivered", "acknowledged"]
    delivered_at: datetime
    acknowledged_at: datetime | None

    @field_validator("delivered_at", "acknowledged_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime | None:
        return None if value is None else _aware_datetime(value)

    @model_validator(mode="after")
    def _coherent(self) -> GrantDeliveryRecord:
        if (self.state == "acknowledged") != (self.acknowledged_at is not None):
            raise ValueError("grant delivery state and acknowledged_at disagree")
        if self.acknowledged_at is not None and self.acknowledged_at < self.delivered_at:
            raise ValueError("grant acknowledgement precedes delivery")
        return self


class EnrollmentRecoveryProjection(_Model):
    proposal: EnrollmentProposal
    approval_decision: ApprovalDecision | None
    grant_delivery: GrantDeliveryRecord | None
    claim: ClaimRecord | None
    source_revision: int = Field(ge=1)
    observed_at: datetime

    @field_validator("observed_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _scope(self) -> EnrollmentRecoveryProjection:
        owner = self.proposal.requested_owner_domain_id
        if self.approval_decision is not None:
            if self.approval_decision.enrollment_id != self.proposal.enrollment_id:
                raise ValueError("projection Decision belongs to another Proposal")
            if self.approval_decision.target_owner_domain_id != owner:
                raise ValueError("projection Decision belongs to another Owner Domain")
        if self.claim is not None and self.claim.device_ref.owner_domain_id != owner:
            raise ValueError("projection Claim belongs to another Owner Domain")
        return self


class AdmissionListCursor(_Model):
    owner_domain_id: OwnerDomainId
    sort_key: datetime
    resource_id: str = Field(min_length=3, max_length=128)

    @field_validator("sort_key", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class EnrollmentProposalQuery(_Model):
    owner_domain_id: OwnerDomainId
    states: tuple[EnrollmentProposalState, ...] = Field(min_length=1)
    cursor: AdmissionListCursor | None
    limit: int = Field(ge=1, le=200)

    @field_validator("states", mode="before")
    @classmethod
    def _states(cls, value: object) -> object:
        value = tuple(value) if isinstance(value, list) else value
        if isinstance(value, tuple) and len(value) != len(set(value)):
            raise ValueError("proposal states must be unique")
        return value

    @model_validator(mode="after")
    def _cursor_scope(self) -> EnrollmentProposalQuery:
        if self.cursor is not None and self.cursor.owner_domain_id != self.owner_domain_id:
            raise ValueError("proposal cursor belongs to another Owner Domain")
        return self


class EnrollmentProposalPage(_Model):
    owner_domain_id: OwnerDomainId
    items: tuple[EnrollmentRecoveryProjection, ...] = Field(default=(), max_length=200)
    next_cursor: AdmissionListCursor | None
    observed_at: datetime

    @field_validator("items", mode="before")
    @classmethod
    def _items(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("observed_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _scope(self) -> EnrollmentProposalPage:
        if (
            self.next_cursor is not None
            and self.next_cursor.owner_domain_id != self.owner_domain_id
        ):
            raise ValueError("proposal page cursor belongs to another Owner Domain")
        if any(
            item.proposal.requested_owner_domain_id != self.owner_domain_id for item in self.items
        ):
            raise ValueError("proposal page contains another Owner Domain")
        return self


class ClaimQuery(_Model):
    owner_domain_id: OwnerDomainId
    states: tuple[ClaimState, ...] = Field(min_length=1)
    cursor: AdmissionListCursor | None
    limit: int = Field(ge=1, le=200)

    @field_validator("states", mode="before")
    @classmethod
    def _states(cls, value: object) -> object:
        value = tuple(value) if isinstance(value, list) else value
        if isinstance(value, tuple) and len(value) != len(set(value)):
            raise ValueError("claim states must be unique")
        return value

    @model_validator(mode="after")
    def _cursor_scope(self) -> ClaimQuery:
        if self.cursor is not None and self.cursor.owner_domain_id != self.owner_domain_id:
            raise ValueError("claim cursor belongs to another Owner Domain")
        return self


class ClaimPage(_Model):
    owner_domain_id: OwnerDomainId
    items: tuple[ClaimRecord, ...] = Field(default=(), max_length=200)
    next_cursor: AdmissionListCursor | None
    observed_at: datetime

    @field_validator("items", mode="before")
    @classmethod
    def _items(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("observed_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _scope(self) -> ClaimPage:
        if (
            self.next_cursor is not None
            and self.next_cursor.owner_domain_id != self.owner_domain_id
        ):
            raise ValueError("claim page cursor belongs to another Owner Domain")
        if any(item.device_ref.owner_domain_id != self.owner_domain_id for item in self.items):
            raise ValueError("claim page contains another Owner Domain")
        return self
