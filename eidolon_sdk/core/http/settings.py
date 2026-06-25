"""Settings for shared HTTP client construction."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class HTTPClientSettings:
    """Small transport-level settings object for ``httpx.AsyncClient``."""

    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0
    trust_env: bool = True

    def to_httpx_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.timeout_seconds,
            connect=self.connect_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class HTTPRetryPolicy:
    """Transport retry settings for service-to-service HTTP clients."""

    attempts: int = 1
    backoff_seconds: float = 0.0
    retry_statuses: tuple[int, ...] = (502, 503, 504)
    retry_methods: tuple[str, ...] = ("GET", "HEAD", "OPTIONS")

    def should_retry_method(self, method: str) -> bool:
        return method.upper() in self.retry_methods
