import httpx
import pytest
from eidolon_sdk.biz.system_data.client import (
    SystemDataRuntimeClient, SystemDataContractError, SystemDataNotFound,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner,person,status", [("other", "p", "active"), ("o", "other", "active"), ("o", "p", "inactive")])
async def test_realm_binding_must_match_request(owner, person, status):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "owner_id": owner, "person_id": person, "realm_id": "r", "status": status, "person_revision": 1,
    }))
    async with httpx.AsyncClient(transport=transport) as http:
        client = SystemDataRuntimeClient(http, "http://test", service_token="secret")
        with pytest.raises(SystemDataContractError):
            await client.get_person_memory_realm(owner_id="o", person_id="p")


@pytest.mark.asyncio
async def test_missing_person_realm_never_falls_back_to_owner():
    requests = []
    def handle(request):
        requests.append(request.url.path)
        return httpx.Response(404, json={"detail": "not bound"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = SystemDataRuntimeClient(http, "http://test", service_token="secret")
        with pytest.raises(SystemDataNotFound):
            await client.get_person_memory_realm(owner_id="o", person_id="p")
    assert requests == ["/api/companion-authority/v1/owners/o/persons/p/memory-realm"]
