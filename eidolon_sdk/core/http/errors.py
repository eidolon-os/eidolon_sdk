"""Shared HTTP exception types."""

from __future__ import annotations


class ServiceHTTPError(Exception):
    """Base class for service-to-service HTTP failures."""


class ServiceUnavailable(ServiceHTTPError):
    """Network-level failure before a valid HTTP response is available."""


class ServiceUpstreamError(ServiceHTTPError):
    """Remote service responded with an unacceptable HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
