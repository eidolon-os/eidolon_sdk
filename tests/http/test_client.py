from __future__ import annotations

import httpx
import pytest

from eidolon_sdk.http import (
    HTTPClientSettings,
    ServiceHTTPClient,
    ServiceUnavailable,
    ServiceUpstreamError,
    create_async_client,
    normalize_base_url,
)


def test_normalize_base_url_strips_trailing_slash() -> None:
    assert normalize_base_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    assert normalize_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"


@pytest.mark.asyncio
async def test_service_http_client_builds_url_and_returns_response() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        response = await ServiceHTTPClient(http, "http://svc.local/")._request(
            "GET",
            "/api/things",
            params={"q": "x"},
        )

    assert response.json() == {"ok": True}
    assert seen == {
        "method": "GET",
        "url": "http://svc.local/api/things?q=x",
    }


@pytest.mark.asyncio
async def test_service_http_client_raises_upstream_for_error_status() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(409, text="conflict"))

    async with httpx.AsyncClient(transport=transport) as http:
        client = ServiceHTTPClient(http, "http://svc.local")
        with pytest.raises(ServiceUpstreamError) as exc_info:
            await client._request("POST", "/api/things")

    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "conflict"


@pytest.mark.asyncio
async def test_service_http_client_honors_strict_ok_statuses() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text="ok"))

    async with httpx.AsyncClient(transport=transport) as http:
        client = ServiceHTTPClient(http, "http://svc.local")
        with pytest.raises(ServiceUpstreamError) as exc_info:
            await client._request("DELETE", "/api/things/1", ok_statuses=(204,))

    assert exc_info.value.status_code == 200
    assert exc_info.value.message == "ok"


@pytest.mark.asyncio
async def test_service_http_client_wraps_network_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ServiceHTTPClient(http, "http://svc.local")
        with pytest.raises(ServiceUnavailable, match="down"):
            await client._request("GET", "/api/things")


@pytest.mark.asyncio
async def test_create_async_client_uses_shared_settings() -> None:
    settings = HTTPClientSettings(
        timeout_seconds=12.0,
        connect_timeout_seconds=3.0,
        trust_env=False,
    )
    client = create_async_client(settings)

    try:
        assert client.timeout.read == 12.0
        assert client.timeout.connect == 3.0
        assert client.trust_env is False
    finally:
        await client.aclose()
