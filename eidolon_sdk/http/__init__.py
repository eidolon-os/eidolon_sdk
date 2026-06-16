"""HTTP client infrastructure shared by Eidolon Python projects."""

from .client import (
    ServiceHTTPClient,
    authorization_header,
    create_async_client,
    normalize_base_url,
)
from .errors import ServiceHTTPError, ServiceUnavailable, ServiceUpstreamError
from .settings import HTTPClientSettings, HTTPRetryPolicy

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
