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


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [None, "owner_id", "person_id", "person_revision", "session_id", "scope"])
async def test_provisional_access_is_bound_to_exact_request(changed):
    payload = {"owner_id": "o", "person_id": "p", "person_revision": 2, "realm_id": "r",
               "session_id": "s", "scope": "provisional_session",
               "policy": {"save_allowed": True, "session_recall_allowed": False}}
    if changed is not None:
        payload[changed] = 3 if changed == "person_revision" else "other"

    def handler(request):
        assert request.url.params["session_id"] == "s"
        assert request.url.params["expected_revision"] == "2"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SystemDataRuntimeClient(http, "http://data", service_token="secret")
        if changed:
            with pytest.raises(SystemDataContractError):
                await client.get_person_provisional_memory_access(
                    owner_id="o", person_id="p", person_revision=2, session_id="s")
        else:
            result = await client.get_person_provisional_memory_access(
                owner_id="o", person_id="p", person_revision=2, session_id="s")
            assert result.policy.save_allowed and not result.policy.session_recall_allowed


@pytest.mark.asyncio
async def test_runtime_client_reads_the_owner_attribution_feed_after_its_cursor() -> None:
    ref = {"owner_id": "owner-a", "session_id": "s", "turn_id": "t", "speech_ms": 2000,
           "source": {"request_id": "t", "session_id": "s", "input_id": "mic", "generation": 1,
                      "sample_rate": 16000, "start_sample": 0, "end_sample": 32000, "channel": "mobile"}}
    change = {"seq": 7, "attribution": {"attribution_id": "va_1", "revision": 1, "owner_id": "owner-a",
                                        "person_id": "p", "person_revision": 1, "refs": [ref],
                                        "source": "turn", "recorded_at": 1.0}}
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        owner = request.url.path.split("/")[5]
        return httpx.Response(200, json={"owner_id": owner, "changes": [change] if owner == "owner-a" else [],
                                         "next_after": 7})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SystemDataRuntimeClient(http, "http://data", service_token="service-token")
        feed = await client.voice_attributions(owner_id="owner-a", after=3)
        assert [c.attribution.person_id for c in feed.changes] == ["p"] and feed.next_after == 7
        assert seen[0].url.path == "/api/companion-authority/v1/owners/owner-a/voiceprints/attributions"
        assert dict(seen[0].url.params) == {"after": "3", "limit": "100"}
        assert seen[0].headers["authorization"] == "Bearer service-token"
        with pytest.raises(SystemDataContractError):
            await client.voice_attributions(owner_id="owner-a", after=9)
