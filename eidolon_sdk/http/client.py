"""Shared async HTTP client primitives."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from .errors import ServiceUnavailable, ServiceUpstreamError
from .settings import HTTPClientSettings


def normalize_base_url(base_url: str) -> str:
    """Return a base URL without trailing slash."""
    return base_url.rstrip("/")


def create_async_client(settings: HTTPClientSettings | None = None) -> httpx.AsyncClient:
    """Create a configured ``httpx.AsyncClient``.

    The SDK keeps this intentionally small: projects own lifecycle and
    service-specific headers, while shared timeout/proxy defaults live here.
    """
    settings = settings or HTTPClientSettings()
    return httpx.AsyncClient(
        timeout=settings.to_httpx_timeout(),
        trust_env=settings.trust_env,
    )


class ServiceHTTPClient:
    """Base class for project-to-project HTTP calls.

    Subclasses define business methods that call ``_request``. The base
    handles URL prepending, network exception wrapping, and status checking.
    It deliberately returns the raw ``httpx.Response`` so callers can choose
    JSON, text, streaming, or custom decoding.
    """

    UNREACHABLE_EXC: ClassVar[type[Exception]] = ServiceUnavailable
    UPSTREAM_EXC: ClassVar[type[ServiceUpstreamError]] = ServiceUpstreamError
    UNREACHABLE_EXCEPTIONS: ClassVar[tuple[type[BaseException], ...]] = (
        httpx.ConnectError,
        httpx.TimeoutException,
    )

    def __init__(self, http_client: httpx.AsyncClient, base_url: str) -> None:
        self._http = http_client
        self._base = normalize_base_url(base_url)

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        ok_statuses: tuple[int, ...] | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(
                method,
                self._url(path),
                json=json,
                params=params,
                timeout=timeout,
            )
        except self.UNREACHABLE_EXCEPTIONS as exc:
            raise self.UNREACHABLE_EXC(str(exc)) from exc

        if ok_statuses is not None:
            if response.status_code not in ok_statuses:
                raise self.UPSTREAM_EXC(response.status_code, response.text)
        elif response.status_code >= 400:
            raise self.UPSTREAM_EXC(response.status_code, response.text)
        return response
