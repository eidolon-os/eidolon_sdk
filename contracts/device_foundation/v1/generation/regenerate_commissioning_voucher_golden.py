#!/usr/bin/env python3
"""Regenerate the commissioning voucher golden.

The vector this replaces (`development-commissioning-identity.json`) described a
per-device factory secret that both the firmware image and a Hub-side registry
file had to carry byte-identically. That mechanism is gone: the base identity is
minted by the Hub during commissioning and bound to the key the device generated
itself, so one firmware image is valid for every unit. See
`docs/设备与Body/设备生命周期状态机与恢复边.md` §4.1.1 and §19.3.24.

Everything here is derived from two stated constants, so any repo can rebuild the
same bytes: the device's operational scalar and the Host's management secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import rfc8785
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from eidolon_sdk.device_foundation.v1 import (
    COMMISSIONING_VOUCHER_KEY_INFO,
    COMMISSIONING_VOUCHER_PURPOSE,
    derive_voucher_signing_key,
)

ROOT = Path(__file__).resolve().parents[1]

# Stated so the vector is reproducible, never so a deployment reuses them.
OPERATIONAL_SCALAR = 0x3456789ABCDEF123456789ABCDEF12
MANAGEMENT_SECRET_HEX = "6f776e65722d646f6d61696e2d6d616e6167656d656e742d7365637265742d31"
DEVICE_BASE_ID = "device-base-" + "4f3b" * 16
SOFTWARE_BASE_ID = "software-body-" + "a71c" * 10
OWNER_DOMAIN_ID = "owner-domain_01"
JTI = "jti-0f3a91c4d25b47e8a6031f7c8b9d2e50"
EXPIRES_AT_UNIX = 1788000000
BASE_KEY_NONCE = "commissioning-nonce-golden-enrolled"


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def raw_signature(key: ec.EllipticCurvePrivateKey, document: object) -> str:
    der = key.sign(
        rfc8785.dumps(document),
        ec.ECDSA(hashes.SHA256(), deterministic_signing=True),
    )
    r, s = decode_dss_signature(der)
    return b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def derived_hardware_identity_ref(device_base_id: str) -> tuple[str, str]:
    canonical = device_base_id.strip().casefold()
    payload = b"eidolon-hardware-identity-v1" + b"\x00" + canonical.encode()
    return payload.decode(), "hardware-" + hashlib.sha256(payload).hexdigest()


def main() -> None:
    key = ec.derive_private_key(OPERATIONAL_SCALAR, ec.SECP256R1())
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    operational_public_key = "p256-spki:" + b64u(spki)
    spki_sha256 = hashlib.sha256(spki).hexdigest()
    device_instance_id = "device-instance-" + spki_sha256

    evidence_document = {
        "device_base_id": DEVICE_BASE_ID,
        "device_instance_id": device_instance_id,
        "operational_public_key": operational_public_key,
        "profile_id": "eidolon-trust-p256-hpke-v1",
    }
    evidence_canonical = rfc8785.dumps(evidence_document).decode()
    evidence_signature = raw_signature(key, evidence_document)
    wire_evidence = f"{evidence_canonical}.{evidence_signature}"

    # The vector is written by the same function its consumers call, so the
    # bytes below cannot be a second spelling of the derivation.
    voucher_key = derive_voucher_signing_key(bytes.fromhex(MANAGEMENT_SECRET_HEX))

    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "base_identity_provenance": "minted",
        "device_base_id": DEVICE_BASE_ID,
        "exp": EXPIRES_AT_UNIX,
        "jti": JTI,
        "operational_spki_sha256": "sha256:" + spki_sha256,
        "owner_domain_id": OWNER_DOMAIN_ID,
        "purpose": COMMISSIONING_VOUCHER_PURPOSE,
    }
    header_canonical = rfc8785.dumps(header).decode()
    claims_canonical = rfc8785.dumps(claims).decode()
    signing_input = f"{b64u(header_canonical.encode())}.{b64u(claims_canonical.encode())}"
    voucher_signature = hmac.new(voucher_key, signing_input.encode(), hashlib.sha256).digest()
    voucher = f"{signing_input}.{b64u(voucher_signature)}"

    base_key_document = {
        "contract": "eidolon.device-foundation.enrolled-base-key-v1",
        "device_base_id": DEVICE_BASE_ID,
        "device_instance_id": device_instance_id,
        "nonce": BASE_KEY_NONCE,
        "owner_domain_id": OWNER_DOMAIN_ID,
    }
    base_key_canonical = rfc8785.dumps(base_key_document).decode()
    base_key_proof = raw_signature(key, base_key_document)

    derivation_input, hardware_identity_ref = derived_hardware_identity_ref(DEVICE_BASE_ID)
    software_derivation_input, software_identity_ref = derived_hardware_identity_ref(
        SOFTWARE_BASE_ID
    )

    vector = {
        "vector_id": "DF-ADMISSION-COMMISSIONING-VOUCHER-001",
        "supersedes": "DF-PH2-REJOIN-IDENTITY-001 (development-commissioning-identity.json)",
        "why": (
            "The device carries no factory identity material. Its base identity is minted "
            "by the Hub during commissioning, delivered over the Controller-witnessed "
            "session, and bound one-to-one to the operational key the device generated "
            "itself. One firmware image is therefore valid for every unit, and no Hub-side "
            "per-device registry exists to drift from it."
        ),
        "device_operational_scalar_hex": f"{OPERATIONAL_SCALAR:x}",
        "operational_public_key": operational_public_key,
        "operational_spki_sha256": "sha256:" + spki_sha256,
        "device_instance_id": device_instance_id,
        "device_base_id": DEVICE_BASE_ID,
        "base_identity_provenance": "minted",
        "hardware_identity_derivation_input_utf8_with_nul_separator": derivation_input,
        "hardware_identity_ref": hardware_identity_ref,
        "software_body_device_base_id": SOFTWARE_BASE_ID,
        "software_body_hardware_identity_derivation_input_utf8_with_nul_separator": (
            software_derivation_input
        ),
        "software_body_hardware_identity_ref": software_identity_ref,
        "evidence_scheme": "hub-issued-base-p256",
        "evidence_document": evidence_document,
        "evidence_canonical_utf8": evidence_canonical,
        "evidence_signature_encoding": "ES256 raw r||s, 64 bytes, base64url without padding",
        "evidence_signature": evidence_signature,
        "wire_evidence": wire_evidence,
        "evidence_digest": "sha256:" + hashlib.sha256(wire_evidence.encode()).hexdigest(),
        "owner_domain_id": OWNER_DOMAIN_ID,
        "voucher": {
            "scheme": "hub-issued-commissioning-voucher-v1",
            "signing_key_derivation": (
                "HKDF-SHA256(host management secret, salt=none, "
                f'info="{COMMISSIONING_VOUCHER_KEY_INFO.decode()}", L=32)'
            ),
            "host_management_secret_hex": MANAGEMENT_SECRET_HEX,
            "signing_key_hex": voucher_key.hex(),
            "header": header,
            "header_canonical_utf8": header_canonical,
            "claims": claims,
            "claims_canonical_utf8": claims_canonical,
            "signing_input": signing_input,
            "compact": voucher,
            "jti": JTI,
            "expires_at_unix": EXPIRES_AT_UNIX,
            "nonce_rule": "commissioning_proof.nonce MUST equal the voucher jti",
        },
        "enrolled_base_key": {
            "scheme": "enrolled-base-key-v1",
            "when": (
                "Continuation inside one Claim lifecycle: resume, retry after the voucher "
                "was consumed or expired, grant re-issue, reconnect. Never a way back into "
                "the queue for a Rejected or Revoked base identity."
            ),
            "signing_document": base_key_document,
            "canonical_utf8": base_key_canonical,
            "proof": base_key_proof,
            "nonce": BASE_KEY_NONCE,
        },
        "must_be_refused": [
            {
                "case": "voucher bound to another operational key",
                "why": "operational_spki_sha256 in the claims is the whole binding",
            },
            {
                "case": "voucher replayed after its jti was consumed",
                "why": "the jti ledger is persistent and survives Hub restart",
            },
            {
                "case": "device reports a device_base_id the Hub never issued",
                "why": "only an issued base identity may enter hardware_identity_ref",
            },
            {
                "case": "second base identity offered for an already bound operational key",
                "why": "base id and operational key are one-to-one, checked at issue and at verify",
            },
            {
                "case": "enrolled-base-key-v1 presented by a Revoked or Rejected base identity",
                "why": "re-entry requires a fresh Controller-witnessed voucher",
            },
        ],
    }

    path = ROOT / "golden" / "commissioning-voucher.json"
    path.write_text(json.dumps(vector, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
