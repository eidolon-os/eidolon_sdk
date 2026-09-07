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

import hashlib
import json

from cryptography.hazmat.primitives.asymmetric import ec

from _vector_helpers import (
    ROOT,
    save,
    signed_document_vector,
    spki,
)

#: The operational key of the device the erase, delivery and acknowledgement
#: goldens all act on.
OPERATIONAL_SCALAR = 0x123456789ABCDEF123456789ABCDEF

CONFIGURATION_NONCE = "Y29uZmlndXJhdGlvbi1ub25jZQ"
ASSERTION_NONCE = "bWFuaWZlc3QtYXNzZXJ0aW9uLW5vbmNl"
#: The board whose Manifest bytes `golden/device-manifest.json` pins first.
ASSERTED_BOARD = "esp32-s3-touch-amoled-2.06"






def asserted_manifest_digest() -> str:
    cases = json.loads(
        (ROOT / "golden" / "device-manifest.json").read_text(encoding="utf-8")
    )["cases"]
    for case in cases:
        if case["board_name"] == ASSERTED_BOARD and not case["has_camera"]:
            return case["digest"]
    raise RuntimeError(f"golden/device-manifest.json publishes no case for {ASSERTED_BOARD}")




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
        signed_document_vector(
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
            signing_key="operational",
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
        signed_document_vector(
            vector_id="DF-DEVICE-CONTROL-MANIFEST-ASSERTION-PROOF-001",
            description=(
                "What a device signs to tell the Authority what it can do. The signed member "
                "is the Manifest's digest, not the document, so the signature cannot carry "
                "from one set of capabilities to another; the digest here is the one "
                "golden/device-manifest.json publishes for "
                f"{ASSERTED_BOARD} without a camera, so the assertion and the document it "
                "asserts move together."
            ),
            signing_key="operational",
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
