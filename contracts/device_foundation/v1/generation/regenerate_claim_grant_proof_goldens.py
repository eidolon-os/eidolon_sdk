#!/usr/bin/env python3
"""Regenerate the two ClaimGrant handoff proof goldens.

Both documents are signed and never sent: only the signature crosses the wire,
so the Authority and the device each build the bytes alone and find out whether
they agreed by whether the signature verifies. That is why the vector is the
artifact and a schema is not — a schema cannot pin member order, and member
order is what a canonicalisation disagreement changes.

The scalars continue the corpus's own rotation, and the acknowledgement is
signed by the operational key of the device the rest of these goldens describe
(`device-instance-591d7c62…`, the one the erase and delivery vectors act on),
so the device_ref it names and the key that signs it are the same device.
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

#: One-time, per-enrollment, software-generated. It is not the device's
#: operational key and must never be: the whole point of the handoff key is
#: that destroying it ends the enrollment without touching the device identity.
HANDOFF_SCALAR = 0x456789ABCDEF123456789ABCDEF123
#: The operational key of the device the erase and delivery goldens describe.
OPERATIONAL_SCALAR = 0x123456789ABCDEF123456789ABCDEF

ENROLLMENT_ID = "enrollment_01"
PROPOSAL_REVISION = 3
COLLECTION_CHALLENGE = "Y29sbGVjdGlvbi1jaGFsbGVuZ2U"
GRANT_ID = "grant_01"


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
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(leaf_paths(item, path))
        return sorted(paths)
    return [prefix]


def vector(
    *,
    vector_id: str,
    description: str,
    signing_key: str,
    key: ec.EllipticCurvePrivateKey,
    document: dict,
) -> dict:
    canonical = rfc8785.dumps(document)
    return {
        "vector_id": vector_id,
        "description": description,
        "signing_key": signing_key,
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
    handoff = ec.derive_private_key(HANDOFF_SCALAR, ec.SECP256R1())
    operational = ec.derive_private_key(OPERATIONAL_SCALAR, ec.SECP256R1())
    device_instance_id = "device-instance-" + hashlib.sha256(spki(operational)).hexdigest()

    save(
        "claim-grant-collection-proof.json",
        vector(
            vector_id="DF-CLAIM-GRANT-COLLECTION-PROOF-001",
            description=(
                "What a device signs with its handoff key to collect the ClaimGrant it was "
                "approved for. The Authority rebuilds these bytes from the Proposal it holds "
                "and verifies the signature over them, so the two ends never exchange the "
                "document — they only find out, at the moment the device asks for its Grant, "
                "whether they built the same one. Until this vector the rule lived in a Python "
                "dict in the Authority and in a hand-concatenated string in the firmware, and "
                "nothing compared them."
            ),
            signing_key="handoff",
            key=handoff,
            document={
                "contract": "eidolon.device-foundation.claim-grant-collection",
                "enrollment_id": ENROLLMENT_ID,
                "proposal_revision": PROPOSAL_REVISION,
                "collection_challenge": COLLECTION_CHALLENGE,
            },
        ),
    )

    save(
        "claim-grant-ack-proof.json",
        vector(
            vector_id="DF-CLAIM-GRANT-ACK-PROOF-001",
            description=(
                "What a device signs with its operational key to acknowledge the ClaimGrant it "
                "opened, which is the step that makes the Claim active. The signing key is the "
                "key `device_ref.device_instance_id` is derived from: the acknowledgement is a "
                "statement by that device about itself, and a proof by any other key would be "
                "a device activating a Claim it is not the subject of."
            ),
            signing_key="operational",
            key=operational,
            document={
                "contract": "eidolon.device-foundation.claim-grant-ack",
                "enrollment_id": ENROLLMENT_ID,
                "grant_id": GRANT_ID,
                "device_ref": {
                    "device_instance_id": device_instance_id,
                    "owner_domain_id": "owner-domain_01",
                    "owner_domain_generation": 3,
                    "claim_generation": 7,
                    "trust_epoch": 4,
                },
            },
        ),
    )


if __name__ == "__main__":
    main()
