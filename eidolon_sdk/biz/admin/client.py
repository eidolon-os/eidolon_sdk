"""HTTP clients for eidolon-admin public runtime contracts.

The SDK owns the wire shape and transport error mapping. Projects still own
when they call admin and how they translate these exceptions into user-facing
behavior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from eidolon_sdk.core.http import ServiceHTTPClient


class AdminClientError(Exception):
    """Base for admin HTTP client failures."""


class AdminNotFound(AdminClientError):
    """Admin returned 404."""


class AdminPrecondition(AdminClientError):
    """Admin returned 409/412: the entity exists but is not ready."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class AdminUpstreamError(AdminClientError):
    """Admin returned a non-2xx response not otherwise classified."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"admin upstream {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class AdminUnreachable(AdminClientError):
    """Connection, DNS, or timeout failure before an HTTP response."""


class AdminResolveError(AdminClientError):
    """Base for /api/resolve failures."""


class AdminResolveNotFound(AdminResolveError):
    """Admin resolve returned 404."""


class AdminResolvePrecondition(AdminResolveError):
    """Admin resolve returned 409/412."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class AdminResolveUpstream(AdminResolveError):
    """Admin resolve returned an unclassified non-2xx response."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"admin upstream {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class AdminResolveUnreachable(AdminResolveError):
    """Connection, DNS, or timeout failure during admin resolve."""


@dataclass(frozen=True, slots=True)
class ResolvedContext:
    """Subset of admin's resolve context used by runtime clients."""

    owner_id: str
    companion_id: str
    memory_realm_id: str
    genome_id: str
    device_id: str | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ResolvedContext":
        if isinstance(data.get("context"), dict):
            data = data["context"]
        return cls(
            owner_id=str(data.get("owner_id") or ""),
            companion_id=str(data.get("companion_id") or ""),
            memory_realm_id=str(data.get("memory_realm_id") or ""),
            genome_id=str(data.get("genome_id") or ""),
            device_id=data.get("device_id"),
        )


def unwrap_detail(body: str) -> str:
    """Strip FastAPI's ``{"detail": ...}`` envelope when present."""
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return body
    if isinstance(parsed, dict) and "detail" in parsed:
        detail = parsed["detail"]
        return detail if isinstance(detail, str) else json.dumps(detail)
    return body


def _quote(value: str) -> str:
    return quote(value, safe="")


class _AdminHTTPBase(ServiceHTTPClient):
    UNREACHABLE_EXC = AdminUnreachable
    UPSTREAM_EXC = AdminUpstreamError

    async def _get_json(
        self,
        path: str,
        *,
        timeout: httpx.Timeout | float | None = 5.0,
        precondition_exc: type[AdminPrecondition] = AdminPrecondition,
        not_found_exc: type[Exception] = AdminNotFound,
        upstream_exc: type[AdminUpstreamError] = AdminUpstreamError,
        unreachable_exc: type[Exception] = AdminUnreachable,
    ) -> dict[str, Any]:
        try:
            response = await self._request("GET", path, timeout=timeout)
        except AdminUnreachable as exc:
            raise unreachable_exc(f"admin GET {path} failed: {exc}") from exc
        except AdminUpstreamError as exc:
            message = unwrap_detail(exc.message)
            if exc.status_code == 404:
                raise not_found_exc(message) from exc
            if exc.status_code in (409, 412):
                raise precondition_exc(exc.status_code, message) from exc
            raise upstream_exc(exc.status_code, message) from exc
        return response.json()


class AdminClient(_AdminHTTPBase):
    """Thin client over admin endpoints used outside admin itself."""

    async def get_owner(self, owner_id: str) -> dict[str, Any]:
        return await self._get_json(f"/api/owners/{_quote(owner_id)}")

    async def resolve_device(self, device_id: str) -> dict[str, Any]:
        return await self._get_json(f"/api/resolve/device/{_quote(device_id)}")


class AdminResolveClient(_AdminHTTPBase):
    """Thin client over admin's ``/api/resolve`` runtime aggregator."""

    async def resolve_owner(self, owner_id: str) -> ResolvedContext:
        data = await self._get_json(
            f"/api/resolve/owner/{_quote(owner_id)}",
            precondition_exc=AdminResolvePrecondition,
            not_found_exc=AdminResolveNotFound,
            upstream_exc=AdminResolveUpstream,
            unreachable_exc=AdminResolveUnreachable,
        )
        return ResolvedContext.from_json(data)

    async def resolve_device(self, device_id: str) -> ResolvedContext:
        data = await self._get_json(
            f"/api/resolve/device/{_quote(device_id)}",
            precondition_exc=AdminResolvePrecondition,
            not_found_exc=AdminResolveNotFound,
            upstream_exc=AdminResolveUpstream,
            unreachable_exc=AdminResolveUnreachable,
        )
        return ResolvedContext.from_json(data)
