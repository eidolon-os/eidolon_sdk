"""Compatibility exports for :mod:`eidolon_sdk.core.http.client`."""

from eidolon_sdk.core.http.client import (
    ServiceHTTPClient,
    authorization_header,
    create_async_client,
    normalize_base_url,
)

__all__ = [
    "ServiceHTTPClient",
    "authorization_header",
    "create_async_client",
    "normalize_base_url",
]
