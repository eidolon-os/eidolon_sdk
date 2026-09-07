#!/usr/bin/env python3
"""Regenerate the two Device Control signing-document goldens.

The same shape as the ClaimGrant proofs one step later on the chain: the device
signs, only the signature travels, and the Authority rebuilds the document from
what it holds. A disagreement is therefore reported as a signature that did not
verify — on the edge that hands a Body its channel, so the visible symptom is a
Claim that is active and a device that never gets a room.

Signed by the operational key of the device the rest of this corpus describes,
so `device_ref.device_instance_id` is the key that signs. The manifest
assertion's `manifest_digest` is a digest `golden/device-manifest.json` already
publishes — the assertion is about that document, so the two move together.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import rfc8785
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

ROOT = Path(__file__).resolve().parents[1]

#: The operational key of the device the erase, delivery and acknowledgement
#: goldens all act on.
OPERATIONAL_SCALAR = 0x123456789ABCDEF123456789ABCDEF

CONFIGURATION_NONCE = "Y29uZmlndXJhdGlvbi1ub25jZQ"
ASSERTION_NONCE = "bWFuaWZlc3QtYXNzZXJ0aW9uLW5vbmNl"
#: The board whose Manifest bytes `golden/device-manifest.json` pins first.
ASSERTED_BOARD = "esp32-s3-touch-amoled-2.06"


def b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def spki(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def raw_signature(key: ec.EllipticCurvePrivateKey, document: object) -> str:
    der = key.sign(
        rfc8785.dumps(document),
        ec.ECDSA(hashes.SHA256(), deterministic_signing=True),
    )
    r, s = decode_dss_signature(der)
    return b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def leaf_paths(value: object, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            paths.extend(leaf_paths(item, f"{prefix}.{key}" if prefix else str(key)))
        return sorted(paths)
    return [prefix]


def asserted_manifest_digest() -> str:
    cases = json.loads(
        (ROOT / "golden" / "device-manifest.json").read_text(encoding="utf-8")
    )["cases"]
    for case in cases:
        if case["board_name"] == ASSERTED_BOARD and not case["has_camera"]:
            return case["digest"]
    raise RuntimeError(f"golden/device-manifest.json publishes no case for {ASSERTED_BOARD}")


def vector(
    *,
    vector_id: str,
    description: str,
    key: ec.EllipticCurvePrivateKey,
    document: dict,
) -> dict:
    canonical = rfc8785.dumps(document)
    return {
        "vector_id": vector_id,
        "description": description,
        "signing_key": "operational",
        "signature_algorithm": "ES256",
        "signature_encoding": "64-byte-r-concat-s-base64url-no-padding",
        "document": document,
        "canonical_utf8": canonical.decode("utf-8"),
        "canonical_sha256": "sha256:" + hashlib.sha256(canonical).hexdigest(),
        "public_key_spki": b64u(spki(key)),
        "key_id": "sha256:" + hashlib.sha256(spki(key)).hexdigest(),
        "signature": raw_signature(key, document),
        "mutate_each_field_must_fail": leaf_paths(document),
    }


def save(name: str, value: dict) -> None:
    (ROOT / "golden" / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote golden/{name}")


def main() -> None:
    operational = ec.derive_private_key(OPERATIONAL_SCALAR, ec.SECP256R1())
    device_ref = {
        "device_instance_id": "device-instance-"
        + hashlib.sha256(spki(operational)).hexdigest(),
        "owner_domain_id": "owner-domain_01",
        "owner_domain_generation": 3,
        "claim_generation": 7,
        "trust_epoch": 4,
    }

    save(
        "device-control-configuration-proof.json",
        vector(
            vector_id="DF-DEVICE-CONTROL-CONFIGURATION-PROOF-001",
            description=(
                "What a device signs to ask the Authority what it should be — the request "
                "behind `configuration:pull`, and so the edge that hands a Body its channel. "
                "Until this vector the rule lived in a Python dict in the Authority, a "
                "hand-concatenated string in the firmware, and an inline map in the phone, "
                "with nothing comparing the three. A device that spelled it differently would "
                "hold an active Claim and never be given a room, which is a state the product "
                "already cannot tell apart from waiting."
            ),
            key=operational,
            document={
                "device_ref": device_ref,
                "nonce": CONFIGURATION_NONCE,
                "operation_type": "device-control.configuration",
            },
        ),
    )

    save(
        "device-control-manifest-assertion-proof.json",
        vector(
            vector_id="DF-DEVICE-CONTROL-MANIFEST-ASSERTION-PROOF-001",
            description=(
                "What a device signs to tell the Authority what it can do. The signed member "
                "is the Manifest's digest, not the document, so the signature cannot carry "
                "from one set of capabilities to another; the digest here is the one "
                "golden/device-manifest.json publishes for "
                f"{ASSERTED_BOARD} without a camera, so the assertion and the document it "
                "asserts move together."
            ),
            key=operational,
            document={
                "device_ref": device_ref,
                "manifest_digest": asserted_manifest_digest(),
                "nonce": ASSERTION_NONCE,
                "operation_type": "device-control.manifest-assert",
            },
        ),
    )


if __name__ == "__main__":
    main()
