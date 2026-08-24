"""Narrow HTTP client for the System Data Companion Runtime Authority."""

from __future__ import annotations

import json
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from eidolon_sdk.core.http import ServiceHTTPClient, authorization_header

from .models import CompanionRuntimeSnapshot


class SystemDataError(Exception):
    """Base error for Runtime Authority calls."""


class SystemDataContractError(SystemDataError):
    """The authority returned a response outside the versioned wire contract."""


class SystemDataNotFound(SystemDataError):
    pass


class SystemDataPrecondition(SystemDataError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class SystemDataUnavailable(SystemDataError):
    pass


class SystemDataUpstreamError(SystemDataError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"system data upstream {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class SystemDataRuntimeClient(ServiceHTTPClient):
    """Consume only the versioned Runtime Snapshot and face read contracts."""

    UNREACHABLE_EXC = SystemDataUnavailable
    UPSTREAM_EXC = SystemDataUpstreamError

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        base_url: str,
        *,
        service_token: str,
    ) -> None:
        if not service_token.strip():
            raise ValueError("System Data service token is required")
        super().__init__(
            http_client,
            base_url,
            default_headers=authorization_header(service_token),
        )

    async def get_companion_runtime(
        self,
        companion_id: str,
        *,
        genome_id: str | None = None,
    ) -> CompanionRuntimeSnapshot:
        params = {"genome_id": genome_id} if genome_id else None
        response = await self._get(
            f"/api/companion-authority/v1/companions/{_quote(companion_id)}/runtime-snapshot",
            params=params,
        )
        return _runtime_snapshot(response)

    async def get_owner_default_runtime(self, owner_id: str) -> CompanionRuntimeSnapshot:
        """The runtime of the Companion this Owner's unaddressed work goes to.

        Named for what it is rather than for how it used to be stored: this was
        the Companion carrying ``role='primary'``, and it is now the one the
        Owner's ``default_companion_id`` points at. The old name described a
        flag that no longer exists.
        """
        response = await self._get(
            f"/api/companion-authority/v1/owners/{_quote(owner_id)}/default-runtime-snapshot"
        )
        return _runtime_snapshot(response)

    async def get_companion_face(self, companion_id: str) -> bytes | None:
        response = await self._get(
            f"/api/companion-authority/v1/companions/{_quote(companion_id)}/face",
            ok_statuses=(200, 204),
        )
        return response.content if response.status_code == 200 else None

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        ok_statuses: tuple[int, ...] | None = None,
    ) -> httpx.Response:
        try:
            return await self._request(
                "GET",
                path,
                params=params,
                ok_statuses=ok_statuses,
            )
        except SystemDataUpstreamError as exc:
            message = _detail(exc.message)
            if exc.status_code == 404:
                raise SystemDataNotFound(message) from exc
            if exc.status_code in {409, 412}:
                raise SystemDataPrecondition(exc.status_code, message) from exc
            raise SystemDataUpstreamError(exc.status_code, message) from exc


def _quote(value: str) -> str:
    return quote(value, safe="")


def _runtime_snapshot(response: httpx.Response) -> CompanionRuntimeSnapshot:
    try:
        payload = response.json()
        return CompanionRuntimeSnapshot.model_validate(payload)
    except (ValueError, ValidationError) as exc:
        raise SystemDataContractError(
            "System Data returned an invalid Companion Runtime Snapshot V1"
        ) from exc


def _detail(body: str) -> str:
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return body
    if isinstance(parsed, dict) and "detail" in parsed:
        value = parsed["detail"]
        return value if isinstance(value, str) else json.dumps(value)
    return body


__all__ = [
    "SystemDataContractError",
    "SystemDataError",
    "SystemDataNotFound",
    "SystemDataPrecondition",
    "SystemDataRuntimeClient",
    "SystemDataUnavailable",
    "SystemDataUpstreamError",
]
