from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from eidolon_sdk.device_foundation.v1 import (
    AuthorityEndpoint,
    AuthorityLocator,
    AuthorityLocatorError,
    LogicalAuthority,
    OwnerDomainDescriptor,
    OwnerDomainTrustAnchor,
    descriptor_key_id,
    sign_descriptor,
)


NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
OWNER_ID = "owner_01"


def _key(scalar: int = 0x123456789ABCDEF) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(scalar, ec.SECP256R1())


def _public_pem(key: ec.EllipticCurvePrivateKey) -> str:
    from cryptography.hazmat.primitives import serialization

    return (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def _anchor(key: ec.EllipticCurvePrivateKey | None = None) -> OwnerDomainTrustAnchor:
    root = key or _key()
    authority = _key(0x3456789ABCDEF12)
    owner_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Eidolon Owner")])
    root_certificate = (
        x509.CertificateBuilder()
        .subject_name(owner_name)
        .issuer_name(owner_name)
        .public_key(root.public_key())
        .serial_number(100)
        .not_valid_before(NOW - timedelta(days=1))
        .not_valid_after(NOW + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .sign(root, hashes.SHA256())
    )
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Eidolon Authority")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(owner_name)
        .public_key(authority.public_key())
        .serial_number(1)
        .not_valid_before(NOW - timedelta(days=1))
        .not_valid_after(NOW + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=True
        )
        .sign(root, hashes.SHA256())
    )
    from cryptography.hazmat.primitives import serialization

    return OwnerDomainTrustAnchor(
        owner_domain_id=OWNER_ID,
        owner_root_certificate_pem=root_certificate.public_bytes(
            serialization.Encoding.PEM
        ).decode("ascii"),
        authority_signing_certificate_pem=certificate.public_bytes(
            serialization.Encoding.PEM
        ).decode("ascii"),
        trust_epoch=4,
    )


def _descriptor(
    *,
    revision: int = 7,
    host: str = "host-a.owner.test",
    key: ec.EllipticCurvePrivateKey | None = None,
    owner_domain_id: str = OWNER_ID,
    operation_path: str = "/device-control/v1",
) -> OwnerDomainDescriptor:
    signing_key = key or _key(0x3456789ABCDEF12)
    key_id = descriptor_key_id(_public_pem(signing_key))
    owner_root_key_id = descriptor_key_id(_public_pem(_key()))
    unsigned = OwnerDomainDescriptor(
        owner_domain_id=owner_domain_id,
        directory_revision=revision,
        trust_root_refs=(owner_root_key_id,),
        endpoints=(
            AuthorityEndpoint(
                authority=LogicalAuthority.ADMISSION,
                logical_audience="eidolon-admission",
                uri=f"https://{host}/device-admission/v1",
                transport_profile="https-json",
                priority=10,
            ),
            AuthorityEndpoint(
                authority=LogicalAuthority.DEVICE_CONTROL,
                logical_audience="eidolon-device-control",
                uri=f"https://{host}{operation_path}",
                transport_profile="https-json",
                priority=10,
            ),
        ),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(days=1),
        signing_key_id=key_id,
        signature="A" * 86,
    )
    return sign_descriptor(unsigned, signing_key)


def _command_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_df_host_001_endpoint_move_preserves_domain_state() -> None:
    locator = AuthorityLocator(_anchor())
    before = {
        "device_instance_id": "device-instance-01",
        "claim_generation": 3,
        "trust_epoch": locator.trust_epoch,
        "mount_revision": 9,
        "assignment_generation": 12,
        "commissioning_state": "closed",
    }
    locator.accept(_descriptor(host="host-a.owner.test"), now=NOW)
    locator.accept(_descriptor(revision=8, host="host-b.owner.test"), now=NOW)

    assert locator.resolve(OWNER_ID, LogicalAuthority.ADMISSION, now=NOW)[0].uri.startswith(
        "https://host-b.owner.test/"
    )
    assert before == {
        "device_instance_id": "device-instance-01",
        "claim_generation": 3,
        "trust_epoch": locator.trust_epoch,
        "mount_revision": 9,
        "assignment_generation": 12,
        "commissioning_state": "closed",
    }


def test_df_host_002_duplicate_and_same_revision_conflict_are_fail_closed() -> None:
    locator = AuthorityLocator(_anchor())
    original = _descriptor()
    locator.accept(original, now=NOW)
    locator.accept(original, now=NOW)

    with pytest.raises(AuthorityLocatorError, match="revision was reused"):
        locator.accept(_descriptor(host="other.owner.test"), now=NOW)


def test_df_host_003_host_loss_resumes_original_operation_id() -> None:
    locator = AuthorityLocator(_anchor())
    operation = {"operation_id": "operation_01", "status": "accepted"}
    locator.accept(_descriptor(host="host-a.owner.test"), now=NOW)
    locator.accept(_descriptor(revision=8, host="host-b.owner.test"), now=NOW)

    assert operation == {"operation_id": "operation_01", "status": "accepted"}
    assert "host-b.owner.test" in locator.resolve(
        OWNER_ID, LogicalAuthority.DEVICE_CONTROL, now=NOW
    )[0].uri


def test_df_host_004_wrong_owner_key_or_signature_never_falls_back_to_tofu() -> None:
    locator = AuthorityLocator(_anchor())
    with pytest.raises(AuthorityLocatorError, match="Owner Domain"):
        locator.accept(_descriptor(owner_domain_id="attacker_owner"), now=NOW)

    attacker = _key(0x987654321)
    with pytest.raises(AuthorityLocatorError, match="signing key"):
        locator.accept(_descriptor(key=attacker), now=NOW)

    valid = _descriptor()
    broken = valid.model_copy(update={"signature": "B" + valid.signature[1:]})
    with pytest.raises(AuthorityLocatorError, match="signature is invalid"):
        locator.accept(broken, now=NOW)
    assert locator.accepted is None


def test_df_host_005_single_host_still_resolves_by_owner_and_authority() -> None:
    locator = AuthorityLocator(_anchor())
    locator.accept(_descriptor(), now=NOW)

    endpoints = locator.resolve(OWNER_ID, LogicalAuthority.ADMISSION, now=NOW)
    assert [(item.authority, item.logical_audience) for item in endpoints] == [
        (LogicalAuthority.ADMISSION, "eidolon-admission")
    ]


def test_df_host_006_host_change_does_not_change_command_fingerprint() -> None:
    command = {
        "command_id": "command_01",
        "owner_domain_id": OWNER_ID,
        "logical_audience": "eidolon-device-control",
        "device_instance_id": "device-instance-01",
        "payload": {"desired_state": "active"},
    }
    before = _command_fingerprint(command)
    locator = AuthorityLocator(_anchor())
    locator.accept(_descriptor(host="192.0.2.10"), now=NOW)
    locator.accept(_descriptor(revision=8, host="host-b.owner.test"), now=NOW)

    assert _command_fingerprint(command) == before


def test_df_host_007_tls_key_cannot_impersonate_lost_owner_root() -> None:
    owner_anchor = _anchor()
    tls_key = _key(0xABCDEF123)
    locator = AuthorityLocator(owner_anchor)

    with pytest.raises(AuthorityLocatorError, match="signing key"):
        locator.accept(_descriptor(key=tls_key), now=NOW)
    with pytest.raises(AuthorityLocatorError, match="AuthorityDiscoveryRequired"):
        locator.resolve(OWNER_ID, LogicalAuthority.ADMISSION, now=NOW)


def test_df_host_008_older_signed_descriptor_cannot_restore_retired_host() -> None:
    locator = AuthorityLocator(_anchor())
    old = _descriptor(revision=7, host="retired.owner.test")
    locator.accept(_descriptor(revision=8, host="active.owner.test"), now=NOW)

    with pytest.raises(AuthorityLocatorError, match="revision rollback"):
        locator.accept(old, now=NOW)
    assert "active.owner.test" in locator.resolve(
        OWNER_ID, LogicalAuthority.ADMISSION, now=NOW
    )[0].uri


def test_expired_descriptor_requires_discovery_without_clearing_claim() -> None:
    locator = AuthorityLocator(_anchor())
    locator.accept(_descriptor(), now=NOW)

    with pytest.raises(AuthorityLocatorError, match="AuthorityDiscoveryRequired"):
        locator.resolve(OWNER_ID, LogicalAuthority.ADMISSION, now=NOW + timedelta(days=2))
    assert locator.accepted is not None


def test_endpoint_priority_not_array_order_selects_first_route() -> None:
    descriptor = _descriptor()
    endpoints = (
        descriptor.endpoints[0].model_copy(
            update={"uri": "https://secondary.owner.test/v1", "priority": 20}
        ),
        descriptor.endpoints[0].model_copy(
            update={"uri": "https://primary.owner.test/v1", "priority": 10}
        ),
    )
    locator = AuthorityLocator(_anchor())
    locator.accept(
        sign_descriptor(
            descriptor.model_copy(update={"endpoints": endpoints}),
            _key(0x3456789ABCDEF12),
        ),
        now=NOW,
    )

    resolved = locator.resolve(OWNER_ID, LogicalAuthority.ADMISSION, now=NOW)
    assert [item.priority for item in resolved] == [10, 20]
