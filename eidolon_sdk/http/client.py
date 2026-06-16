"""Shared async HTTP client primitives."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import httpx

from .errors import ServiceUnavailable, ServiceUpstreamError
from .settings import HTTPClientSettings, HTTPRetryPolicy


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


def authorization_header(token: str, *, scheme: str = "Bearer") -> dict[str, str]:
    """Return an HTTP Authorization header for a token."""
    value = token.strip()
    if not value:
        raise ValueError("authorization token is required")
    scheme = scheme.strip()
    if scheme and not value.lower().startswith(f"{scheme.lower()} "):
        value = f"{scheme} {value}"
    return {"Authorization": value}


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

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        base_url: str,
        *,
        default_headers: dict[str, str] | None = None,
        retry_policy: HTTPRetryPolicy | None = None,
    ) -> None:
        self._http = http_client
        self._base = normalize_base_url(base_url)
        self._default_headers = dict(default_headers or {})
        self._retry_policy = retry_policy or HTTPRetryPolicy()

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        ok_statuses: tuple[int, ...] | None = None,
        retry_policy: HTTPRetryPolicy | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> httpx.Response:
        merged_headers = {**self._default_headers, **(headers or {})}
        policy = retry_policy or self._retry_policy
        attempts = max(1, policy.attempts)
        can_retry = policy.should_retry_method(method)
        last_unreachable: BaseException | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self._http.request(
                    method,
                    self._url(path),
                    json=json,
                    params=params,
                    headers=merged_headers or None,
                    timeout=timeout,
                )
            except self.UNREACHABLE_EXCEPTIONS as exc:
                last_unreachable = exc
                if not can_retry or attempt >= attempts:
                    raise self.UNREACHABLE_EXC(str(exc)) from exc
                await _sleep_before_retry(policy, attempt)
                continue

            if _response_ok(response, ok_statuses):
                return response

            should_retry_status = (
                can_retry
                and response.status_code in policy.retry_statuses
                and attempt < attempts
            )
            if should_retry_status:
                await response.aclose()
                await _sleep_before_retry(policy, attempt)
                continue
            raise self.UPSTREAM_EXC(response.status_code, response.text)

        if last_unreachable is not None:
            raise self.UNREACHABLE_EXC(str(last_unreachable)) from last_unreachable
        raise RuntimeError("unreachable HTTP retry state")

    async def health_check(
        self,
        path: str = "/health",
        *,
        ok_statuses: tuple[int, ...] = (200,),
        timeout: httpx.Timeout | float | None = 2.0,
    ) -> bool:
        """Return whether a service health endpoint responds acceptably."""
        try:
            await self._request("GET", path, ok_statuses=ok_statuses, timeout=timeout)
        except (self.UNREACHABLE_EXC, self.UPSTREAM_EXC):
            return False
        return True


def _response_ok(response: httpx.Response, ok_statuses: tuple[int, ...] | None) -> bool:
    if ok_statuses is not None:
        return response.status_code in ok_statuses
    return response.status_code < 400


async def _sleep_before_retry(policy: HTTPRetryPolicy, attempt: int) -> None:
    if policy.backoff_seconds <= 0:
        return
    await asyncio.sleep(policy.backoff_seconds * attempt)
