"""Compatibility exports for :mod:`eidolon_sdk.core.http`."""

from eidolon_sdk.core.http import (
    HTTPClientSettings,
    HTTPRetryPolicy,
    ServiceHTTPClient,
    ServiceHTTPError,
    ServiceUnavailable,
    ServiceUpstreamError,
    authorization_header,
    create_async_client,
    normalize_base_url,
)

__all__ = [
    "HTTPClientSettings",
    "HTTPRetryPolicy",
    "ServiceHTTPClient",
    "ServiceHTTPError",
    "ServiceUnavailable",
    "ServiceUpstreamError",
    "authorization_header",
    "create_async_client",
    "normalize_base_url",
]
