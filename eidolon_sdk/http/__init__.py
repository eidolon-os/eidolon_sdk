"""HTTP client infrastructure shared by Eidolon Python projects."""

from .client import ServiceHTTPClient, create_async_client, normalize_base_url
from .errors import ServiceHTTPError, ServiceUnavailable, ServiceUpstreamError
from .settings import HTTPClientSettings

__all__ = [
    "HTTPClientSettings",
    "ServiceHTTPClient",
    "ServiceHTTPError",
    "ServiceUnavailable",
    "ServiceUpstreamError",
    "create_async_client",
    "normalize_base_url",
]
