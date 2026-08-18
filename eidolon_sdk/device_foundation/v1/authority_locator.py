"""Host-independent Owner Domain directory core.

This module is the canonical Python binding for ``OwnerDomainDescriptor`` and
the reference implementation of ``AuthorityLocatorPort``.  It deliberately has
no DNS, HTTP, mDNS, filesystem, or database dependency: adapters obtain
candidate descriptors and persist accepted state outside this boundary.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol, runtime_checkable

import rfc8785
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LogicalAuthority(str, Enum):
    ADMISSION = "admission"
    DEVICE_CONTROL = "device-control"
    BODY_MESH = "body-mesh"
    COMPANION = "companion"


class AuthorityEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    authority: LogicalAuthority
    logical_audience: str = Field(min_length=1, max_length=128)
    uri: str = Field(pattern=r"^https://", max_length=2048)
    transport_profile: str = Field(pattern=r"^(https-json|mqtt-tls|nats-tls)$")
    priority: int = Field(ge=0, le=65535)


class OwnerDomainDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    owner_domain_id: str = Field(min_length=1, max_length=128)
    directory_revision: int = Field(ge=1)
    trust_root_refs: tuple[str, ...] = Field(min_length=1)
    endpoints: tuple[AuthorityEndpoint, ...] = Field(min_length=1)
    issued_at: datetime
    expires_at: datetime
    signing_key_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    signature: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")

    @field_validator("trust_root_refs")
    @classmethod
    def _valid_unique_roots(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("trust_root_refs must be unique")
        if any(
            len(item) != 71
            or not item.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in item[7:])
            for item in value
        ):
            raise ValueError("trust_root_refs must be lowercase SHA-256 digests")
        return value

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _utc_instants(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("descriptor instants must include an offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _valid_window_and_endpoints(self) -> OwnerDomainDescriptor:
        if self.expires_at <= self.issued_at:
            raise ValueError("descriptor expires_at must be after issued_at")
        identities = [
            (endpoint.authority, endpoint.logical_audience, endpoint.uri)
            for endpoint in self.endpoints
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("descriptor endpoints must be unique")
        return self

    def signing_document(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"signature"})

    def canonical_signing_bytes(self) -> bytes:
        return rfc8785.dumps(self.signing_document())


class OwnerDomainTrustAnchor(BaseModel):
    """Public Owner root installed only by commissioning or root rotation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    owner_domain_id: str = Field(min_length=1, max_length=128)
    owner_root_certificate_pem: str = Field(min_length=1, max_length=4096)
    authority_signing_certificate_pem: str = Field(min_length=1, max_length=4096)
    trust_epoch: int = Field(ge=1)

    @property
    def key_id(self) -> str:
        return descriptor_key_id(
            self.owner_root_key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("ascii")
        )

    @property
    def owner_root_certificate(self) -> x509.Certificate:
        try:
            return x509.load_pem_x509_certificate(
                self.owner_root_certificate_pem.encode("ascii")
            )
        except ValueError as exc:
            raise AuthorityLocatorError("Owner root certificate is invalid") from exc

    @property
    def owner_root_key(self) -> ec.EllipticCurvePublicKey:
        key = self.owner_root_certificate.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise AuthorityLocatorError("Owner root key must be P-256")
        return key

    @property
    def authority_key(self) -> ec.EllipticCurvePublicKey:
        try:
            certificate = x509.load_pem_x509_certificate(
                self.authority_signing_certificate_pem.encode("ascii")
            )
        except ValueError as exc:
            raise AuthorityLocatorError("authority signing certificate is invalid") from exc
        key = certificate.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise AuthorityLocatorError("authority signing key must be P-256")
        return key

    @property
    def authority_key_id(self) -> str:
        key = self.authority_key
        return descriptor_key_id(
            key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("ascii")
        )

    def validate_delegation(self, *, now: datetime) -> None:
        root_certificate = self.owner_root_certificate
        certificate = x509.load_pem_x509_certificate(
            self.authority_signing_certificate_pem.encode("ascii")
        )
        now = _utc(now)
        if now < root_certificate.not_valid_before_utc or now >= root_certificate.not_valid_after_utc:
            raise AuthorityLocatorError("Owner root certificate is not valid now")
        if now < certificate.not_valid_before_utc or now >= certificate.not_valid_after_utc:
            raise AuthorityLocatorError("authority signing certificate is not valid now")
        try:
            root_constraints = root_certificate.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value
            constraints = certificate.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value
            usage = certificate.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage
            ).value
        except x509.ExtensionNotFound as exc:
            raise AuthorityLocatorError(
                "authority signing certificate lacks constrained usage"
            ) from exc
        if not root_constraints.ca:
            raise AuthorityLocatorError("Owner root certificate is not a CA")
        if constraints.ca or x509.oid.ExtendedKeyUsageOID.CODE_SIGNING not in usage:
            raise AuthorityLocatorError(
                "authority signing certificate is not a descriptor-signing leaf"
            )
        root = self.owner_root_key
        try:
            root.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                ec.ECDSA(certificate.signature_hash_algorithm),
            )
        except InvalidSignature as exc:
            raise AuthorityLocatorError(
                "authority signing certificate is not delegated by Owner root"
            ) from exc


class AuthorityLocatorError(ValueError):
    """A candidate directory is not safe to accept or resolve."""


@runtime_checkable
class AuthorityLocatorPort(Protocol):
    def accept(self, candidate: OwnerDomainDescriptor, *, now: datetime) -> None: ...

    def resolve(
        self, owner_domain_id: str, authority: LogicalAuthority, *, now: datetime
    ) -> tuple[AuthorityEndpoint, ...]: ...


def _public_key(public_key_pem: str) -> ec.EllipticCurvePublicKey:
    key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise AuthorityLocatorError("Owner Domain key must be P-256")
    return key


def descriptor_key_id(public_key_pem: str) -> str:
    key = _public_key(public_key_pem)
    spki = key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return "sha256:" + hashlib.sha256(spki).hexdigest()


def _raw_signature(signature: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(signature + "==")
    except (ValueError, TypeError) as exc:
        raise AuthorityLocatorError("descriptor signature is not base64url") from exc
    if len(raw) != 64:
        raise AuthorityLocatorError("descriptor signature must be 64-byte P1363")
    return raw


def sign_descriptor(
    descriptor: OwnerDomainDescriptor,
    private_key: ec.EllipticCurvePrivateKey,
) -> OwnerDomainDescriptor:
    if not isinstance(private_key.curve, ec.SECP256R1):
        raise AuthorityLocatorError("Owner Domain key must be P-256")
    key_id = descriptor_key_id(
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    unsigned = descriptor.model_copy(update={"signing_key_id": key_id})
    der = private_key.sign(
        unsigned.canonical_signing_bytes(),
        ec.ECDSA(hashes.SHA256(), deterministic_signing=True),
    )
    r, s = decode_dss_signature(der)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    signature = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return unsigned.model_copy(update={"signature": signature})


def verify_descriptor(
    descriptor: OwnerDomainDescriptor,
    trust_anchor: OwnerDomainTrustAnchor,
) -> None:
    if descriptor.owner_domain_id != trust_anchor.owner_domain_id:
        raise AuthorityLocatorError("descriptor Owner Domain does not match trust anchor")
    if descriptor.signing_key_id != trust_anchor.authority_key_id:
        raise AuthorityLocatorError("descriptor signing key is not delegated by the Owner root")
    if trust_anchor.key_id not in descriptor.trust_root_refs:
        raise AuthorityLocatorError("descriptor does not retain the commissioned Owner root")
    raw = _raw_signature(descriptor.signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    try:
        trust_anchor.authority_key.verify(
            der,
            descriptor.canonical_signing_bytes(),
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature as exc:
        raise AuthorityLocatorError("descriptor signature is invalid") from exc


class AuthorityLocator(AuthorityLocatorPort):
    """Pure state machine for accepting and resolving signed directories."""

    def __init__(
        self,
        trust_anchor: OwnerDomainTrustAnchor,
        accepted: OwnerDomainDescriptor | None = None,
    ) -> None:
        self._trust_anchor = trust_anchor
        self._accepted: OwnerDomainDescriptor | None = None
        if accepted is not None:
            self.accept(accepted, now=accepted.issued_at)

    @property
    def accepted(self) -> OwnerDomainDescriptor | None:
        return self._accepted

    @property
    def trust_epoch(self) -> int:
        return self._trust_anchor.trust_epoch

    def accept(self, candidate: OwnerDomainDescriptor, *, now: datetime) -> None:
        now = _utc(now)
        self._trust_anchor.validate_delegation(now=now)
        verify_descriptor(candidate, self._trust_anchor)
        if now < candidate.issued_at:
            raise AuthorityLocatorError("descriptor is not yet valid")
        if now >= candidate.expires_at:
            raise AuthorityLocatorError("descriptor is expired")
        current = self._accepted
        if current is not None:
            if candidate.directory_revision < current.directory_revision:
                raise AuthorityLocatorError("descriptor directory revision rollback")
            if (
                candidate.directory_revision == current.directory_revision
                and candidate != current
            ):
                raise AuthorityLocatorError("descriptor revision was reused with different content")
        self._accepted = candidate

    def resolve(
        self, owner_domain_id: str, authority: LogicalAuthority, *, now: datetime
    ) -> tuple[AuthorityEndpoint, ...]:
        now = _utc(now)
        if owner_domain_id != self._trust_anchor.owner_domain_id:
            raise AuthorityLocatorError("requested Owner Domain is not commissioned")
        descriptor = self._accepted
        if descriptor is None:
            raise AuthorityLocatorError("AuthorityDiscoveryRequired")
        if now >= descriptor.expires_at:
            raise AuthorityLocatorError("AuthorityDiscoveryRequired")
        endpoints = tuple(
            sorted(
                (item for item in descriptor.endpoints if item.authority == authority),
                key=lambda item: (item.priority, item.logical_audience, item.uri),
            )
        )
        if not endpoints:
            raise AuthorityLocatorError(f"descriptor has no {authority.value} endpoint")
        return endpoints


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuthorityLocatorError("trusted time must include an offset")
    return value.astimezone(UTC)
