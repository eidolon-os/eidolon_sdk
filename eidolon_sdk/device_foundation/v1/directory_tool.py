"""Offline issuer for immutable Owner Domain directory artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .authority_locator import (
    AuthorityEndpoint,
    AuthorityLocatorError,
    OwnerDomainDescriptor,
    OwnerDomainTrustAnchor,
    sign_descriptor,
)


def issue_descriptor(
    source: dict[str, object],
    *,
    owner_root_certificate_pem: str,
    authority_signing_certificate_pem: str,
    authority_private_key_pem: bytes,
) -> OwnerDomainDescriptor:
    try:
        private_key = serialization.load_pem_private_key(
            authority_private_key_pem, password=None
        )
    except (TypeError, ValueError) as exc:
        raise AuthorityLocatorError("authority signing private key is invalid") from exc
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
        private_key.curve, ec.SECP256R1
    ):
        raise AuthorityLocatorError("authority signing private key must be P-256")
    trust = OwnerDomainTrustAnchor(
        owner_domain_id=str(source["owner_domain_id"]),
        owner_root_certificate_pem=owner_root_certificate_pem,
        authority_signing_certificate_pem=authority_signing_certificate_pem,
        trust_epoch=int(source["trust_epoch"]),
    )
    if trust.authority_key.public_numbers() != private_key.public_key().public_numbers():
        raise AuthorityLocatorError(
            "authority signing private key does not match delegated certificate"
        )
    descriptor = OwnerDomainDescriptor(
        owner_domain_id=trust.owner_domain_id,
        owner_domain_generation=int(source["owner_domain_generation"]),
        directory_revision=int(source["directory_revision"]),
        descriptor_uri=str(source["descriptor_uri"]),
        trust_root_refs=(trust.key_id,),
        endpoints=tuple(
            AuthorityEndpoint.model_validate_json(json.dumps(item))
            for item in source["endpoints"]  # type: ignore[union-attr]
        ),
        issued_at=datetime.fromisoformat(str(source["issued_at"]).replace("Z", "+00:00")),
        expires_at=datetime.fromisoformat(str(source["expires_at"]).replace("Z", "+00:00")),
        signing_key_id=trust.authority_key_id,
        signature="A" * 86,
    )
    trust.validate_delegation(now=descriptor.issued_at)
    return sign_descriptor(descriptor, private_key)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--owner-root-certificate", type=Path, required=True)
    parser.add_argument("--authority-signing-certificate", type=Path, required=True)
    parser.add_argument("--authority-private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    descriptor = issue_descriptor(
        source,
        owner_root_certificate_pem=args.owner_root_certificate.read_text(encoding="ascii"),
        authority_signing_certificate_pem=args.authority_signing_certificate.read_text(
            encoding="ascii"
        ),
        authority_private_key_pem=args.authority_private_key.read_bytes(),
    )
    encoded = json.dumps(
        descriptor.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
    ) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
