"""Compatibility exports for :mod:`eidolon_sdk.biz.devices`."""

from eidolon_sdk.biz.devices import (
    DeviceAuthError,
    DeviceAuthHeaders,
    body_sha256_hex,
    canonical_request,
    public_key_fingerprint,
    verify_device_signature,
)

__all__ = [
    "DeviceAuthError",
    "DeviceAuthHeaders",
    "body_sha256_hex",
    "canonical_request",
    "public_key_fingerprint",
    "verify_device_signature",
]
