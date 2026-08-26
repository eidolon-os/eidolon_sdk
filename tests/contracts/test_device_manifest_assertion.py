"""A device's capabilities are its own, current, re-assertable account.

The Manifest used to be captured once, at enrollment, and was thereafter
immutable for the life of the Claim. That made a firmware upgrade unable to say
what it had become: the only path to a corrected Manifest was to remove the
device and add it again, which needs a person standing next to the hardware.

The Owner approves an *identity*. What that identity can do is the device's own
declaration, and it changes when the firmware does.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
import rfc8785
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from pydantic import ValidationError

from eidolon_sdk.device_foundation.v1 import (
    AssertDeviceManifest,
    DeviceManifestAcceptance,
    DeviceRef,
    ManifestDocument,
    ManifestRef,
    OwnerDomainId,
    manifest_digest,
    derive_device_instance_id,
)
from eidolon_sdk.device_foundation.v1.device_erase import (
    DeviceEraseContractError,
    verify_p256_signature,
)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


_DEVICE = derive_device_instance_id("p256-spki:MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE")


def _device_ref() -> DeviceRef:
    return DeviceRef(
        device_instance_id=_DEVICE,
        owner_domain_id=OwnerDomainId("owner-domain-1"),
        owner_domain_generation=1,
        claim_generation=2,
        trust_epoch=1,
    )


def _document(*, camera: bool) -> dict[str, object]:
    media = [{"kind": "audio"}] + ([{"kind": "video"}] if camera else [])
    return {"schema_version": 1, "media": media, "properties": [], "actions": [], "events": []}


def _manifest(*, revision: int, camera: bool) -> ManifestDocument:
    document = _document(camera=camera)
    return ManifestDocument(
        manifest_id="esp-box-3",
        revision=revision,
        digest=manifest_digest(document),
        document=document,
    )


def _signed(manifest: ManifestDocument) -> tuple[AssertDeviceManifest, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    spki = _b64(
        key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    unsigned = {
        "device_ref": _device_ref().model_dump(mode="json"),
        "manifest_digest": manifest.digest,
        "nonce": "nonce-000000000000000",
        "operation_type": "device-control.manifest-assert",
    }
    signature = key.sign(rfc8785.dumps(unsigned), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(signature)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return (
        AssertDeviceManifest(
            device_ref=_device_ref(),
            manifest=manifest,
            nonce="nonce-000000000000000",
            public_key_spki=spki,
            device_signature=_b64(raw),
        ),
        spki,
    )


def test_manifest_digest_is_the_rfc8785_digest_of_the_document() -> None:
    document = _document(camera=True)
    expected = "sha256:" + hashlib.sha256(rfc8785.dumps(document)).hexdigest()
    assert manifest_digest(document) == expected


def test_a_manifest_cannot_declare_a_digest_it_does_not_have() -> None:
    """The one invariant every producer of a Manifest was re-checking by hand."""

    document = _document(camera=False)
    with pytest.raises(ValidationError, match="digest"):
        ManifestDocument(
            manifest_id="esp-box-3",
            revision=1,
            digest=manifest_digest(_document(camera=True)),
            document=document,
        )


def test_assertion_signature_covers_the_reference_the_nonce_and_the_content() -> None:
    manifest = _manifest(revision=2, camera=True)
    assertion, spki = _signed(manifest)
    verify_p256_signature(
        public_key_spki=spki,
        signing_document=assertion.signing_document(),
        signature=assertion.device_signature,
    )

    # Same liveness proof, different capabilities: the signature must not carry.
    swapped = assertion.model_copy(update={"manifest": _manifest(revision=2, camera=False)})
    with pytest.raises(DeviceEraseContractError):
        verify_p256_signature(
            public_key_spki=spki,
            signing_document=swapped.signing_document(),
            signature=swapped.device_signature,
        )


def test_acceptance_distinguishes_a_change_from_a_repeat() -> None:
    accepted = DeviceManifestAcceptance(
        device_ref=_device_ref(),
        nonce="nonce-000000000000000",
        accepted=ManifestRef(
            manifest_id="esp-box-3", revision=2, digest=manifest_digest(_document(camera=True))
        ),
        outcome="accepted",
        accepted_at="2026-08-25T10:00:00Z",
    )
    assert accepted.outcome == "accepted"
    unchanged = accepted.model_copy(update={"outcome": "unchanged"})
    assert unchanged.accepted == accepted.accepted


def test_every_manifest_model_parses_its_own_wire_form() -> None:
    """The round-trip invariant, applied at the point a new contract is added."""

    manifest = _manifest(revision=3, camera=True)
    assertion, _ = _signed(manifest)
    for model in (manifest, assertion):
        assert type(model).model_validate(model.model_dump(mode="json")) == model
        assert type(model).model_validate_json(model.model_dump_json()) == model
