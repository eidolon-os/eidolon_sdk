#!/usr/bin/env python3
"""Regenerate PH2 goldens after the intentional DeviceRef breaking correction."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import rfc8785
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "golden" / name).read_text(encoding="utf-8"))


def save(name: str, value: dict) -> None:
    (ROOT / "golden" / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def raw_signature(key: ec.EllipticCurvePrivateKey, document: object) -> str:
    der = key.sign(
        rfc8785.dumps(document),
        ec.ECDSA(hashes.SHA256(), deterministic_signing=True),
    )
    r, s = decode_dss_signature(der)
    return base64.urlsafe_b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).rstrip(b"=").decode()


def main() -> None:
    revoke = load("claim-revoke.json")
    encoded = rfc8785.dumps(revoke["fingerprint_document"])
    revoke["canonical_fingerprint_utf8"] = encoded.decode()
    revoke["fingerprint"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    save("claim-revoke.json", revoke)

    erase = load("device-local-erase.json")
    erase_key = ec.derive_private_key(0x123456789ABCDEF123456789ABCDEF, ec.SECP256R1())
    spki = erase_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    erase["public_key_spki"] = base64.urlsafe_b64encode(spki).rstrip(b"=").decode()
    erase["key_id"] = "sha256:" + hashlib.sha256(spki).hexdigest()
    operation = rfc8785.dumps(erase["operation"])
    erase["operation_canonical_utf8"] = operation.decode()
    erase["operation_fingerprint"] = "sha256:" + hashlib.sha256(operation).hexdigest()
    erase["ack_canonical_utf8"] = rfc8785.dumps(erase["ack_signing_document"]).decode()
    erase["ack_signature"] = raw_signature(erase_key, erase["ack_signing_document"])
    erase["key_proof_signature"] = raw_signature(erase_key, erase["key_proof_signing_document"])
    save("device-local-erase.json", erase)

    descriptor = load("owner-domain-descriptor.json")
    descriptor_key = ec.derive_private_key(0x23456789ABCDEF123456789ABCDEF1, ec.SECP256R1())
    public_pem = descriptor_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    descriptor["authority_signing_spki_pem"] = public_pem
    spki = descriptor_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    descriptor["descriptor"]["signing_key_id"] = "sha256:" + hashlib.sha256(spki).hexdigest()
    signing_document = {key: value for key, value in descriptor["descriptor"].items() if key != "signature"}
    descriptor["canonical_signing_utf8"] = rfc8785.dumps(signing_document).decode()
    descriptor["descriptor"]["signature"] = raw_signature(descriptor_key, signing_document)
    save("owner-domain-descriptor.json", descriptor)

    aad = load("claim-grant-aad.json")
    encoded = rfc8785.dumps(aad["aad"])
    aad["canonical_aad_sha256"] = hashlib.sha256(encoded).hexdigest()
    aad["ciphertext"] = AESGCM(bytes.fromhex(aad["test_key"])).encrypt(
        bytes.fromhex(aad["test_nonce"]), bytes.fromhex(aad["plaintext"]), encoded
    ).hex()
    save("claim-grant-aad.json", aad)


if __name__ == "__main__":
    main()
