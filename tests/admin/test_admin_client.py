from __future__ import annotations

import httpx
import pytest

from eidolon_sdk.admin import (
    AdminClient,
    AdminNotFound,
    AdminPrecondition,
    AdminResolveClient,
    AdminResolveNotFound,
    AdminResolvePrecondition,
    AdminResolveUnreachable,
    AdminResolveUpstream,
    AdminUnreachable,
    AdminUpstreamError,
    ResolvedContext,
)


def _expected_context() -> dict:
    return {
        "tenant_id": "default",
        "user_id": "manson",
        "agent_id": "ag_1",
        "template_id": "caretaker",
        "memory_mcp_url": "http://127.0.0.1:8031/mcp",
        "device_id": None,
        "ignored": "extra",
    }


def test_resolved_context_unwraps_admin_envelope() -> None:
    ctx = ResolvedContext.from_json({"context": _expected_context()})

    assert ctx.tenant_id == "default"
    assert ctx.user_id == "manson"
    assert ctx.agent_id == "ag_1"
    assert ctx.template_id == "caretaker"
    assert ctx.memory_mcp_url == "http://127.0.0.1:8031/mcp"
    assert ctx.device_id is None


def test_resolved_context_accepts_flat_shape() -> None:
    assert ResolvedContext.from_json(_expected_context()).user_id == "manson"


@pytest.mark.asyncio
async def test_admin_client_quotes_path_and_returns_user_json() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"spec": {"user_id": "alice/bob"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        body = await AdminClient(http, "http://admin.local").get_user("alice/bob")

    assert seen["url"] == "http://admin.local/api/users/alice%2Fbob"
    assert body["spec"]["user_id"] == "alice/bob"


@pytest.mark.asyncio
async def test_admin_client_maps_error_statuses_with_detail_unwrap() -> None:
    responses = iter(
        [
            httpx.Response(404, json={"detail": "missing"}),
            httpx.Response(412, json={"detail": "not bound"}),
            httpx.Response(500, json={"detail": {"code": "boom"}}),
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: next(responses))
    ) as http:
        client = AdminClient(http, "http://admin.local")
        with pytest.raises(AdminNotFound, match="missing"):
            await client.get_user("ghost")
        with pytest.raises(AdminPrecondition) as precondition:
            await client.resolve_device("dev")
        with pytest.raises(AdminUpstreamError) as upstream:
            await client.get_user("alice")

    assert precondition.value.status_code == 412
    assert precondition.value.message == "not bound"
    assert upstream.value.status_code == 500
    assert upstream.value.message == '{"code": "boom"}'


@pytest.mark.asyncio
async def test_admin_client_wraps_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(AdminUnreachable, match="admin GET /api/users/alice failed"):
            await AdminClient(http, "http://admin.local").get_user("alice")


@pytest.mark.asyncio
async def test_admin_resolve_client_maps_runtime_errors_and_context() -> None:
    responses = iter(
        [
            httpx.Response(200, json={"context": _expected_context()}),
            httpx.Response(404, json={"detail": "unknown"}),
            httpx.Response(409, json={"detail": "inactive"}),
            httpx.Response(503, text="maintenance"),
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: next(responses))
    ) as http:
        client = AdminResolveClient(http, "http://admin.local/")
        assert (await client.resolve_user("manson")).user_id == "manson"
        with pytest.raises(AdminResolveNotFound, match="unknown"):
            await client.resolve_user("ghost")
        with pytest.raises(AdminResolvePrecondition) as precondition:
            await client.resolve_device("dev")
        with pytest.raises(AdminResolveUpstream) as upstream:
            await client.resolve_device("dev")

    assert precondition.value.status_code == 409
    assert precondition.value.message == "inactive"
    assert upstream.value.status_code == 503
    assert upstream.value.message == "maintenance"


@pytest.mark.asyncio
async def test_admin_resolve_client_uses_runtime_unreachable_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(AdminResolveUnreachable, match="admin GET"):
            await AdminResolveClient(http, "http://admin.local").resolve_user("alice")
