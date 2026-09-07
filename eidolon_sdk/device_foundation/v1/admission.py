"""Canonical PH2 Admission bindings with nominal identities and closed states."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from typing import Any, Final, Literal

import rfc8785
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .lifecycle import (
    DeviceInstanceId,
    WireEnum,
    ActorRef,
    BusinessOwnerId,
    DeviceRef,
    ManifestDocument,
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
    device_instance_candidate_id: DeviceInstanceId
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
    """Possession of the operational key that one issued base identity is bound to.

    ``hub-issued-base-p256`` is the whole of V1: the device carries no factory
    material, so what it can prove is that it holds the key the Hub bound to the
    base identity it was issued. ``manufacturer-attestation-p256`` answers a
    different question — which physical board this is — and is never a
    substitute for the first.
    """

    scheme: Literal["hub-issued-base-p256", "manufacturer-attestation-p256"]
    evidence: str = Field(min_length=16, max_length=65536)
    evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CommissioningProof(_Model):
    """Standing to ask, which is not the same question as approval.

    ``hub-issued-commissioning-voucher-v1`` carries the one-shot voucher the Hub
    signed during a Controller-witnessed commissioning; ``nonce`` is that
    voucher's ``jti``. ``enrolled-base-key-v1`` carries a signature by the
    already recorded operational key and continues one Claim lifecycle — it is
    not a way back into the queue for a Revoked or Rejected base identity.
    """

    scheme: Literal["hub-issued-commissioning-voucher-v1", "enrolled-base-key-v1"]
    proof: str = Field(min_length=16, max_length=4096)
    nonce: str = Field(min_length=16, max_length=256)


#: Domain separation for the commissioning voucher signing key.
#:
#: The Host signs vouchers with a key derived from the management secret it
#: already holds, rather than a second file nobody would remember to rotate.
#: This ``info`` is the whole of what stops a management credential — minted
#: from that same secret for ``ADMISSION_AUDIENCE`` — from being replayed as a
#: commissioning proof, so it is a security boundary and not a label.
COMMISSIONING_VOUCHER_KEY_INFO = b"eidolon-commissioning-voucher-v1"

#: The ``purpose`` claim inside the voucher. Equal to the key info by value and
#: independent of it by meaning: one separates keys, the other is a signed
#: claim a verifier checks.
COMMISSIONING_VOUCHER_PURPOSE = "eidolon-commissioning-voucher-v1"


def derive_voucher_signing_key(management_secret: bytes) -> bytes:
    """The voucher signing key, derived once for every Python caller.

    Admin derives this to sign a voucher and Hub derives it to verify one, from
    the same management secret and never from anything sent between them. So
    the two never compare intermediate values, and a disagreement about this
    derivation is not reported as a disagreement: it arrives as a device
    refused at first commissioning, with a valid signature by the wrong key and
    no field anywhere naming what differs.

    Both sides are Python and both already import this package, so this is one
    implementation rather than two that agree. The bytes are pinned in
    ``golden/commissioning-voucher.json`` against a stated management secret,
    and this function is what the vector is checked against — so the vector and
    its callers cannot agree by coincidence.
    """

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=COMMISSIONING_VOUCHER_KEY_INFO,
    ).derive(management_secret)


#: The JOSE header every commissioning voucher is signed under.
#:
#: Part of the signed bytes rather than decoration: the verifier requires this
#: mapping exactly, so an added ``kid`` or a changed ``alg`` on the issuing side
#: is refused with no mention of a header.
COMMISSIONING_VOUCHER_HEADER: Final[dict[str, str]] = {"alg": "HS256", "typ": "JWT"}

#: How the base identity in a voucher came to exist. ``minted`` is a first
#: commissioning; ``derived-from-controller`` re-signs an identity this Owner
#: Domain already issued to this very key, which is what lets a removed Body
#: come back as itself rather than as a stranger.
COMMISSIONING_VOUCHER_PROVENANCE: Final = frozenset(
    {"minted", "derived-from-controller"}
)

#: The complete claim set. A verifier holds a voucher to exactly these members,
#: so a claim added on the issuing side is refused as a member-set mismatch —
#: which is why this is one frozenset and not a list on each side.
COMMISSIONING_VOUCHER_CLAIM_NAMES: Final = frozenset(
    {
        "base_identity_provenance",
        "device_base_id",
        "exp",
        "jti",
        "operational_spki_sha256",
        "owner_domain_id",
        "purpose",
    }
)


def commissioning_voucher_claims(
    *,
    device_base_id: str,
    owner_domain_id: str,
    operational_spki_sha256: str,
    jti: str,
    expires_at_unix: int,
    provenance: str = "minted",
) -> dict[str, Any]:
    """The claims a commissioning voucher carries, built once for every caller.

    Nothing compares these member-for-member across the wire. Admin assembles
    them, signs the RFC 8785 bytes and sends a compact token; Hub decodes it and
    requires the member set to equal what it independently believes the set to
    be. So a claim added, renamed or dropped on one side is never reported as a
    claim problem — it is a device refused at the first commissioning it cannot
    retry past, with the refusal naming a signature or nothing at all.

    That is why this is a function and not a convention. The Host's own policy
    — how ``jti`` is minted, how long the window is, whether a base identity is
    new — stays with the caller; the shape of what gets signed does not.

    ``operational_spki_sha256`` binds the voucher to one operational key and is
    the whole of its value: without it, anything that read the token once could
    exchange it for standing under a key of its own.
    """

    if provenance not in COMMISSIONING_VOUCHER_PROVENANCE:
        raise ValueError(
            f"unknown base identity provenance {provenance!r}; "
            f"expected one of {sorted(COMMISSIONING_VOUCHER_PROVENANCE)}"
        )
    claims = {
        "base_identity_provenance": provenance,
        "device_base_id": device_base_id,
        "exp": int(expires_at_unix),
        "jti": jti,
        "operational_spki_sha256": operational_spki_sha256,
        "owner_domain_id": owner_domain_id,
        "purpose": COMMISSIONING_VOUCHER_PURPOSE,
    }
    # The member set a verifier enforces and the members built here are two
    # statements of one fact, so they are checked against each other rather
    # than left to agree. Only a change to one of the two constants above can
    # trip this, and the alternative to tripping is a voucher every verifier
    # refuses for a reason none of them can name.
    if set(claims) != COMMISSIONING_VOUCHER_CLAIM_NAMES:
        raise AssertionError(
            "commissioning voucher claim set disagrees with "
            "COMMISSIONING_VOUCHER_CLAIM_NAMES: built "
            f"{sorted(claims)}, declared {sorted(COMMISSIONING_VOUCHER_CLAIM_NAMES)}"
        )
    return claims


def sign_commissioning_voucher(*, claims: dict[str, Any], signing_key: bytes) -> str:
    """The compact voucher: ``b64(header).b64(claims).b64(HMAC)``.

    Both segments are RFC 8785, because a verifier that re-derives the
    canonical form — as Hub does — rejects any other member order, and a JSON
    Schema cannot pin member order at all. That makes the framing a contract
    and not an implementation detail, which is why it lives here rather than
    being hand-concatenated at each producer.

    Deliberately takes a key rather than a management secret, and does not
    validate ``claims``: a caller that needs a deliberately malformed voucher —
    a verifier's own negative tests — must be able to build one, and a caller
    that needs a well-formed one has ``commissioning_voucher_claims`` above.
    """

    signing_input = "{}.{}".format(
        _b64url(rfc8785.dumps(COMMISSIONING_VOUCHER_HEADER)),
        _b64url(rfc8785.dumps(claims)),
    )
    signature = hmac.new(signing_key, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class HandoffPublicKey(_Model):
    scheme: Literal["DHKEM-P256-HKDF-SHA256"] = "DHKEM-P256-HKDF-SHA256"
    public_key: str = Field(pattern=r"^p256-spki:[A-Za-z0-9_-]+$")


class OperationalPublicKey(_Model):
    scheme: Literal["ES256-P256"] = "ES256-P256"
    public_key: str = Field(pattern=r"^p256-spki:[A-Za-z0-9_-]+$")


class CreateEnrollment(_Model):
    profile_id: Literal["eidolon-trust-p256-hpke-v1"] = "eidolon-trust-p256-hpke-v1"
    device_instance_candidate_id: DeviceInstanceId
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


#: The document a device signs with its handoff key to collect its ClaimGrant.
CLAIM_GRANT_COLLECTION_PROOF_CONTRACT = "eidolon.device-foundation.claim-grant-collection"

#: The document a device signs with its operational key to acknowledge it.
CLAIM_GRANT_ACK_PROOF_CONTRACT = "eidolon.device-foundation.claim-grant-ack"


def claim_grant_collection_proof_document(
    *,
    enrollment_id: str,
    proposal_revision: int,
    collection_challenge: str,
) -> dict[str, Any]:
    """What the handoff key signs, built once for every Python caller.

    Neither end sends this document: the Authority rebuilds it from the
    Proposal it holds and verifies a signature over its RFC 8785 bytes, so the
    two implementations discover a disagreement only as an unverifiable proof —
    a device refused at the one step it cannot retry its way out of, with
    nothing anywhere saying the two spelled the same thing differently. Which
    is why the bytes are a golden (``golden/claim-grant-collection-proof.json``)
    rather than a schema: nothing validates this on a wire, and a schema could
    not pin member order in any case.
    """

    return {
        "contract": CLAIM_GRANT_COLLECTION_PROOF_CONTRACT,
        "enrollment_id": enrollment_id,
        "proposal_revision": proposal_revision,
        "collection_challenge": collection_challenge,
    }


def claim_grant_ack_proof_document(
    *,
    enrollment_id: str,
    grant_id: str,
    device_ref: DeviceRef,
) -> dict[str, Any]:
    """What the operational key signs to make the Claim active.

    The signing key is the key ``device_ref.device_instance_id`` is derived
    from, so this is the named device speaking about itself. Takes the
    ``DeviceRef`` model rather than a mapping: the nested member set is part of
    the signed bytes, and a caller that assembled it by hand would be the
    second definition this function exists to remove.
    """

    return {
        "contract": CLAIM_GRANT_ACK_PROOF_CONTRACT,
        "enrollment_id": enrollment_id,
        "grant_id": grant_id,
        "device_ref": device_ref.model_dump(mode="json"),
    }


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
    device_instance_id: DeviceInstanceId
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
