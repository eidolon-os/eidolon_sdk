import asyncio

import httpx
import pytest

from eidolon_sdk.core.http import create_async_client, request_with_reconnect


@pytest.mark.asyncio
@pytest.mark.parametrize("method,opt_in,expected", [("GET", False, 2), ("POST", True, 2), ("POST", False, 1), ("PUT", False, 1)])
async def test_only_safe_reads_replay_identical_body(method, opt_in, expected):
    seen = []
    async def handler(request):
        seen.append(request.content)
        if len(seen) == 1:
            raise httpx.RemoteProtocolError("Server disconnected")
        return httpx.Response(200)
    async with create_async_client(transport=httpx.MockTransport(handler)) as client:
        if expected == 1:
            with pytest.raises(httpx.RemoteProtocolError):
                await request_with_reconnect(client, method, "http://test/query", timeout=1, replay_safe=opt_in, json={"query": "devices"})
        else:
            assert (await request_with_reconnect(client, method, "http://test/query", timeout=1, replay_safe=opt_in, json={"query": "devices"})).status_code == 200
    assert len(seen) == expected
    assert all(body == seen[0] for body in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected", [(httpx.RemoteProtocolError, 2), (httpx.ReadTimeout, 1)])
async def test_bounded_attempts(failure, expected):
    calls = 0
    async def handler(request):
        nonlocal calls
        calls += 1
        raise failure("failed")
    async with create_async_client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(failure):
            await request_with_reconnect(client, "GET", "http://test", timeout=1)
    assert calls == expected


@pytest.mark.asyncio
async def test_reconnect_shares_total_deadline():
    calls = 0
    async def handler(request):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.04)
        raise httpx.RemoteProtocolError("closed")
    async with create_async_client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ReadTimeout):
            await request_with_reconnect(client, "GET", "http://test", timeout=0.06)
    assert calls == 2


@pytest.mark.asyncio
async def test_status_refusals_are_not_replayed():
    calls = 0
    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503)
    async with create_async_client(transport=httpx.MockTransport(handler)) as client:
        assert (await request_with_reconnect(client, "GET", "http://test", timeout=1)).status_code == 503
    assert calls == 1


@pytest.mark.asyncio
async def test_consumed_stream_is_not_replayed():
    calls = 0
    async def content():
        yield b"one shot"
    async def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.RemoteProtocolError("closed")
    async with create_async_client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.RemoteProtocolError):
            await request_with_reconnect(client, "POST", "http://test", timeout=1, replay_safe=True, content=content())
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("uds", [None, "/tmp/test.sock"])
async def test_tcp_and_uds_expire_before_server_idle_timeout(uds):
    async with create_async_client(uds=uds) as client:
        assert client._transport._pool._keepalive_expiry == 2.0
