from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from eidolon_sdk.devices import (
    DeviceAuthError,
    DeviceAuthHeaders,
    body_sha256_hex,
    canonical_request,
    public_key_fingerprint,
    verify_device_signature,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _signed_headers(
    *,
    device_id: str = "esp32-1",
    path_query: str = "/api/config",
    nonce: str = "nonce-1",
    timestamp: str = "0",
    key=None,
    include_public_key: bool = True,
) -> tuple[DeviceAuthHeaders, str]:
    key = key or ec.generate_private_key(ec.SECP256R1())
    public_der = key.public_key().public_bytes(
        Encoding.DER,
        PublicFormat.SubjectPublicKeyInfo,
    )
    public_key = _b64url(public_der)
    signed = canonical_request(
        method="GET",
        path_query=path_query,
        device_id=device_id,
        nonce=nonce,
        timestamp=timestamp,
        body_hash=body_sha256_hex(),
    )
    headers = DeviceAuthHeaders(
        device_id=device_id,
        nonce=nonce,
        timestamp=timestamp,
        public_key=public_key if include_public_key else None,
        signature=_b64url(key.sign(signed, ec.ECDSA(hashes.SHA256()))),
    )
    return headers, public_key


def test_verify_device_signature_accepts_non_get_method() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    public_der = key.public_key().public_bytes(
        Encoding.DER,
        PublicFormat.SubjectPublicKeyInfo,
    )
    public_key = _b64url(public_der)
    signed = canonical_request(
        method="POST",
        path_query="/api/control",
        device_id="esp32-1",
        nonce="nonce-1",
        timestamp="0",
        body_hash=body_sha256_hex(b'{"op":"config.refresh"}'),
    )
    headers = DeviceAuthHeaders(
        device_id="esp32-1",
        nonce="nonce-1",
        timestamp="0",
        public_key=public_key,
        signature=_b64url(key.sign(signed, ec.ECDSA(hashes.SHA256()))),
    )

    assert verify_device_signature(
        headers=headers,
        stored_public_key=None,
        path_query="/api/control",
        method="POST",
        body=b'{"op":"config.refresh"}',
    ) == public_key_fingerprint(public_key)


def test_verify_device_signature_accepts_first_registration() -> None:
    headers, public_key = _signed_headers()

    fingerprint = verify_device_signature(
        headers=headers,
        stored_public_key=None,
        path_query="/api/config",
    )

    assert fingerprint == public_key_fingerprint(public_key)


def test_verify_device_signature_uses_stored_public_key_after_registration() -> None:
    headers, public_key = _signed_headers(include_public_key=False)

    fingerprint = verify_device_signature(
        headers=headers,
        stored_public_key=public_key,
        path_query="/api/config",
    )

    assert fingerprint.startswith("p256:")


def test_verify_device_signature_rejects_bad_signature_and_stale_timestamp() -> None:
    headers, _public_key = _signed_headers()
    bad = DeviceAuthHeaders(
        device_id=headers.device_id,
        nonce=headers.nonce,
        timestamp=headers.timestamp,
        public_key=headers.public_key,
        signature="not-valid",
    )
    with pytest.raises(DeviceAuthError, match="invalid device signature"):
        verify_device_signature(headers=bad, stored_public_key=None, path_query="/api/config")

    stale, _ = _signed_headers(timestamp="1700000000")
    with pytest.raises(DeviceAuthError, match="stale"):
        verify_device_signature(
            headers=stale,
            stored_public_key=None,
            path_query="/api/config",
            now=1_800_000_000,
        )
