"""Compatibility exports for :mod:`eidolon_sdk.biz.devices.auth`."""

from eidolon_sdk.biz.devices.auth import (
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
