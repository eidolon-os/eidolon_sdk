from __future__ import annotations

import httpx
import pytest

from eidolon_sdk.biz.system_data import (
    SystemDataContractError,
    SystemDataNotFound,
    SystemDataPrecondition,
    SystemDataRuntimeClient,
    SystemDataUnavailable,
    SystemDataUpstreamError,
)


def _runtime_snapshot() -> dict:
    return {
        "contract_version": "1",
        "operation": "companion.runtime-snapshot",
        "owner_id": "owner-a",
        "companion_id": "companion-a",
        "lifecycle_state": "active",
        "runtime_config": {"model": "local-model"},
        "memory_realm": {
            "realm_id": "realm-a",
            "lifecycle_state": "active",
        },
        "persona_genome": {
            "genome_id": "genome-a",
            "version": 3,
            "lifecycle_state": "committed",
            "schema_version": "eidolon.persona_genome",
            "genome_hash": "pg_hash",
            "realizer_version": "eidolon.persona_realizer",
            "genome": {"schema_version": "eidolon.persona_genome"},
        },
    }


@pytest.mark.asyncio
async def test_runtime_client_reads_exact_snapshots_and_face() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/face"):
            return httpx.Response(200, content=b"jpeg", headers={"Content-Type": "image/jpeg"})
        return httpx.Response(200, json=_runtime_snapshot())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SystemDataRuntimeClient(
            http,
            "http://data.local/",
            service_token="service-token-with-at-least-24-chars",
        )
        current = await client.get_companion_runtime("companion/a")
        pinned = await client.get_companion_runtime("companion/a", genome_id="genome/a")
        primary = await client.get_owner_default_runtime("owner/a")
        face = await client.get_companion_face("companion/a")

    assert current.owner_id == "owner-a"
    assert current.persona_genome.genome_id == "genome-a"
    assert current.runtime_config == {"model": "local-model"}
    assert pinned == current
    assert primary == current
    assert face == b"jpeg"
    assert seen[0].headers["Authorization"] == "Bearer service-token-with-at-least-24-chars"
    assert seen[0].url.raw_path.endswith(b"/companions/companion%2Fa/runtime-snapshot")
    assert seen[1].url.params["genome_id"] == "genome/a"
    assert seen[2].url.raw_path.endswith(b"/owners/owner%2Fa/default-runtime-snapshot")


@pytest.mark.asyncio
async def test_runtime_client_maps_absent_face_and_authority_errors() -> None:
    responses = iter(
        [
            httpx.Response(204),
            httpx.Response(404, json={"detail": "missing"}),
            httpx.Response(412, json={"detail": "inactive"}),
            httpx.Response(500, text="boom"),
        ]
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: next(responses))
    ) as http:
        client = SystemDataRuntimeClient(
            http,
            "http://data.local",
            service_token="service-token-with-at-least-24-chars",
        )
        assert await client.get_companion_face("companion-a") is None
        with pytest.raises(SystemDataNotFound, match="missing"):
            await client.get_companion_runtime("missing")
        with pytest.raises(SystemDataPrecondition, match="inactive"):
            await client.get_companion_runtime("inactive")
        with pytest.raises(SystemDataUpstreamError) as upstream:
            await client.get_owner_default_runtime("owner-a")

    assert upstream.value.status_code == 500


@pytest.mark.parametrize("status_code", [401, 403])
@pytest.mark.asyncio
async def test_runtime_client_does_not_map_credential_failure_to_absence(
    status_code: int,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, json={"detail": "denied"})
        )
    ) as http:
        client = SystemDataRuntimeClient(
            http,
            "http://data.local",
            service_token="service-token-with-at-least-24-chars",
        )
        with pytest.raises(SystemDataUpstreamError) as denied:
            await client.get_companion_runtime("companion-a")

    assert denied.value.status_code == status_code


@pytest.mark.asyncio
async def test_runtime_client_maps_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SystemDataRuntimeClient(
            http,
            "http://data.local",
            service_token="service-token-with-at-least-24-chars",
        )
        with pytest.raises(SystemDataUnavailable, match="down"):
            await client.get_companion_runtime("companion-a")


@pytest.mark.asyncio
async def test_runtime_client_rejects_response_outside_wire_contract() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"owner_id": "owner-a"})
        )
    ) as http:
        client = SystemDataRuntimeClient(
            http,
            "http://data.local",
            service_token="service-token-with-at-least-24-chars",
        )
        with pytest.raises(SystemDataContractError, match="Runtime Snapshot V1"):
            await client.get_companion_runtime("companion-a")


def test_runtime_client_requires_service_token() -> None:
    with pytest.raises(ValueError, match="service token"):
        SystemDataRuntimeClient(httpx.AsyncClient(), "http://data.local", service_token="")
