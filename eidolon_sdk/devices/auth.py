"""Device request signing helpers for ESP32 config and control requests."""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key


class DeviceAuthError(ValueError):
    """Raised when a device request signature cannot be trusted."""


@dataclass(frozen=True)
class DeviceAuthHeaders:
    device_id: str
    nonce: str
    timestamp: str
    public_key: str | None
    signature: str


def body_sha256_hex(body: bytes = b"") -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_request(
    *,
    method: str,
    path_query: str,
    device_id: str,
    nonce: str,
    timestamp: str,
    body_hash: str,
) -> bytes:
    return "\n".join(
        [
            method.upper(),
            path_query,
            device_id,
            nonce,
            timestamp,
            body_hash,
        ]
    ).encode("utf-8")


def public_key_fingerprint(public_key_b64: str) -> str:
    der = _b64url_decode(public_key_b64)
    return "p256:" + hashlib.sha256(der).hexdigest()


def verify_device_signature(
    *,
    headers: DeviceAuthHeaders,
    stored_public_key: str | None,
    path_query: str,
    body: bytes = b"",
    now: int | None = None,
) -> str:
    """Verify a signed device request and return its public key fingerprint.

    First registration is TOFU: when ``stored_public_key`` is absent the
    request must carry ``X-Device-Public-Key``. Later requests are verified
    against the stored public key; if a public key is sent again it must match.
    """

    public_key_b64 = headers.public_key or stored_public_key
    if not public_key_b64:
        raise DeviceAuthError("X-Device-Public-Key is required for first registration")
    if stored_public_key and headers.public_key and headers.public_key != stored_public_key:
        raise DeviceAuthError("device public key mismatch")

    _check_timestamp(headers.timestamp, now=now)

    try:
        public_key = load_der_public_key(_b64url_decode(public_key_b64))
    except Exception as exc:
        raise DeviceAuthError("invalid device public key") from exc
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise DeviceAuthError("device public key must be an EC key")
    if public_key.curve.name not in {"secp256r1", "prime256v1"}:
        raise DeviceAuthError("device public key must use P-256")

    signed = canonical_request(
        method="GET",
        path_query=path_query,
        device_id=headers.device_id,
        nonce=headers.nonce,
        timestamp=headers.timestamp,
        body_hash=body_sha256_hex(body),
    )
    try:
        public_key.verify(_b64url_decode(headers.signature), signed, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise DeviceAuthError("invalid device signature") from exc
    except Exception as exc:
        raise DeviceAuthError("invalid device signature encoding") from exc

    return public_key_fingerprint(public_key_b64)


def _check_timestamp(timestamp: str, *, now: int | None = None) -> None:
    try:
        value = int(timestamp)
    except ValueError as exc:
        raise DeviceAuthError("invalid X-Device-Timestamp") from exc
    if value < 0:
        raise DeviceAuthError("invalid X-Device-Timestamp")

    # ESP32 may request config before SNTP has corrected wall-clock time. If it
    # sends a plausible Unix timestamp, enforce a small freshness window;
    # otherwise replay protection falls back to signed nonce tracking.
    unix_floor = 1_700_000_000
    if value >= unix_floor:
        current = int(time.time()) if now is None else now
        if abs(current - value) > 300:
            raise DeviceAuthError("stale X-Device-Timestamp")


def _b64url_decode(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))
