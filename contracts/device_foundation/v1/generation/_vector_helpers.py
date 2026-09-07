"""What the golden generators had each copied.

These scripts are hand-run and are not part of the published contract — nothing
globs them into the catalog and no gate calls them. That is why the duplication
went unnoticed: `raw_signature`, `b64u`, `spki`, `leaf_paths` and `save` were
written out again in each new generator, in the same directory, while the work
those generators exist for was removing hand-written copies of documents. The
cost was never operational; it was that the next generator would copy them once
more.

Deliberately only what was actually shared. A generator's own inputs — the
scalars, the identifiers, the reason a particular document looks the way it
does — stay in the generator, where a reader looking for why a vector says what
it says will find them.
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


def b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def spki(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def raw_signature(key: ec.EllipticCurvePrivateKey, document: object) -> str:
    """ES256 over the document's RFC 8785 bytes, as 64-byte R||S base64url.

    Deterministic (RFC 6979) so regenerating a vector that nothing else changed
    reproduces it byte for byte — which is how a regeneration proves it changed
    only what the author meant to change.
    """

    der = key.sign(
        rfc8785.dumps(document),
        ec.ECDSA(hashes.SHA256(), deterministic_signing=True),
    )
    r, s = decode_dss_signature(der)
    return b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def leaf_paths(value: object, prefix: str = "") -> list[str]:
    """Every position in a document that carries a value, dotted."""

    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            paths.extend(leaf_paths(item, f"{prefix}.{key}" if prefix else str(key)))
        return sorted(paths)
    return [prefix]


def signed_document_vector(
    *,
    vector_id: str,
    description: str,
    signing_key: str,
    key: ec.EllipticCurvePrivateKey,
    document: dict,
) -> dict:
    """A vector for a document that is signed and never sent.

    The negative matrix is derived from the document rather than restated, so a
    member added to the document and forgotten cannot be a member whose
    mutation nobody proves is rejected.
    """

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
