from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from eidolon_sdk.biz.runtime import (
    RuntimeTokenRevokedError,
    RuntimeTokenVerifier,
    RuntimeUnauthenticatedError,
    device_revocation_keys,
    jti_revocation_keys,
    owner_revocation_keys,
    resolve_shared_secret,
    session_revocation_keys,
    sign_runtime_token,
)


SECRET = "test-secret-with-enough-entropy-32b"


class MemoryRevocationStore:
    def __init__(self, keys: set[str] | None = None) -> None:
        self._keys = keys or set()

    async def get(self, key: str) -> bytes | None:
        return b"revoked" if key in self._keys else None


def _sign(**kwargs):
    device_id = kwargs.pop("device_id", "device-1")
    return sign_runtime_token(
        secret=SECRET,
        actor_kind="device",
        actor_id=device_id,
        device_id=device_id,
        owner_id=kwargs.pop("owner_id", "owner-a"),
        companion_id=kwargs.pop("companion_id", "companion-a"),
        memory_realm_id=kwargs.pop("memory_realm_id", "realm-a"),
        genome_id=kwargs.pop("genome_id", "genome-a"),
        **kwargs,
    )


def test_sign_runtime_token_pins_device_payload_schema() -> None:
    token, exp = _sign(
        device_id="web-123",
        owner_id="owner-a",
        companion_id="companion-a",
        memory_realm_id="realm-a",
        genome_id="genome-a",
        scopes=("device", "voice"),
        ttl_seconds=60,
    )

    payload = jwt.decode(token, SECRET, algorithms=["HS256"])

    assert payload["device_id"] == "web-123"
    assert payload["runtime_token_version"] == 2
    assert payload["actor_kind"] == "device"
    assert payload["actor_id"] == "web-123"
    assert payload["owner_id"] == "owner-a"
    assert payload["companion_id"] == "companion-a"
    assert payload["memory_realm_id"] == "realm-a"
    assert payload["genome_id"] == "genome-a"
    assert payload["scopes"] == ["device", "voice"]
    assert isinstance(payload["jti"], str)
    assert datetime.fromtimestamp(payload["exp"], tz=timezone.utc) == exp.replace(microsecond=0)
    assert payload["iat"] <= payload["exp"]


def test_sign_runtime_token_rejects_empty_secret() -> None:
    with pytest.raises(ValueError, match="secret is required"):
        sign_runtime_token(
            secret="",
            actor_kind="device",
            actor_id="device-1",
            device_id="device-1",
            owner_id="owner-a",
            companion_id="companion-a",
            memory_realm_id="realm-a",
            genome_id="genome-a",
        )


def test_sign_runtime_token_requires_identity_claims() -> None:
    with pytest.raises(ValueError, match="owner_id is required"):
        _sign(owner_id="")


def test_runtime_token_verifier_rejects_empty_secret() -> None:
    with pytest.raises(ValueError, match="secret is required"):
        RuntimeTokenVerifier(secret="")


@pytest.mark.asyncio
async def test_runtime_token_verifier_round_trips_runtime_identity() -> None:
    token, exp = _sign(scopes=("device",), session_id="session-1", ttl_seconds=60)

    verified = await RuntimeTokenVerifier(secret=SECRET).verify(token)

    assert verified.device_id == "device-1"
    assert verified.actor_kind == "device"
    assert verified.actor_id == "device-1"
    assert verified.session_id == "session-1"
    assert verified.owner_id == "owner-a"
    assert verified.companion_id == "companion-a"
    assert verified.memory_realm_id == "realm-a"
    assert verified.genome_id == "genome-a"
    assert verified.scopes == ("device",)
    assert verified.exp == exp.replace(microsecond=0)


@pytest.mark.asyncio
async def test_runtime_token_verifier_rejects_wrong_secret() -> None:
    token, _exp = _sign()

    with pytest.raises(RuntimeUnauthenticatedError, match="invalid token"):
        await RuntimeTokenVerifier(secret="wrong-secret-with-enough-bytes-32").verify(token)


@pytest.mark.asyncio
async def test_runtime_token_verifier_rejects_expired_token() -> None:
    token, _exp = _sign(ttl_seconds=-1)

    with pytest.raises(RuntimeUnauthenticatedError, match="expired"):
        await RuntimeTokenVerifier(secret=SECRET).verify(token)


@pytest.mark.asyncio
async def test_runtime_token_verifier_checks_device_and_owner_revocations() -> None:
    device_token, _exp = _sign(device_id="1c:db:a1")
    device_store = MemoryRevocationStore({device_revocation_keys("1c:db:a1")[0]})

    with pytest.raises(RuntimeTokenRevokedError, match="device revoked"):
        await RuntimeTokenVerifier(secret=SECRET, revocation_kv=device_store).verify(
            device_token
        )

    owner_token, _exp = _sign(owner_id="owner-a")
    owner_store = MemoryRevocationStore({owner_revocation_keys("owner-a")[0]})

    with pytest.raises(RuntimeTokenRevokedError, match="all sessions revoked"):
        await RuntimeTokenVerifier(secret=SECRET, revocation_kv=owner_store).verify(owner_token)


def test_revocation_keys_are_canonical_encoded_keys() -> None:
    assert device_revocation_keys("device-1") == ("revoked.device.ZGV2aWNlLTE",)
    assert device_revocation_keys("1c:db:a1") == ("revoked.device.MWM6ZGI6YTE",)
    assert owner_revocation_keys("owner-a") == ("revoked.owner.b3duZXItYQ",)
    assert session_revocation_keys("web/s1") == ("revoked.session.d2ViL3Mx",)
    assert jti_revocation_keys("jti-1") == ("revoked.jti.anRpLTE",)


def test_resolve_shared_secret_prefers_argument_then_file(tmp_path) -> None:
    secret_file = tmp_path / "jwt-secret"
    secret_file.write_text(" from-file \n", encoding="utf-8")

    assert resolve_shared_secret(" from-arg ", secret_file=secret_file) == "from-arg"
    assert resolve_shared_secret("", secret_file=secret_file) == "from-file"
    assert resolve_shared_secret("", secret_file=tmp_path / "missing") == ""


@pytest.mark.asyncio
async def test_runtime_token_verifier_accepts_owner_actor_without_device_id() -> None:
    token, exp = sign_runtime_token(
        secret=SECRET,
        actor_kind="owner",
        actor_id="owner-a",
        owner_id="owner-a",
        companion_id="companion-a",
        memory_realm_id="realm-a",
        genome_id="genome-a",
        scopes=("web",),
        ttl_seconds=60,
    )

    verified = await RuntimeTokenVerifier(secret=SECRET).verify(token)

    assert verified.actor_kind == "owner"
    assert verified.actor_id == "owner-a"
    assert verified.device_id is None
    assert verified.owner_id == "owner-a"
    assert verified.companion_id == "companion-a"
    assert verified.memory_realm_id == "realm-a"
    assert verified.genome_id == "genome-a"
    assert verified.scopes == ("web",)
    assert verified.exp == exp.replace(microsecond=0)


@pytest.mark.asyncio
async def test_runtime_token_verifier_requires_actor_claims() -> None:
    exp = datetime.now(timezone.utc) + timedelta(seconds=60)
    token = jwt.encode({"exp": int(exp.timestamp())}, SECRET, algorithm="HS256")

    verifier = RuntimeTokenVerifier(secret=SECRET)

    with pytest.raises(RuntimeUnauthenticatedError, match="missing actor_kind"):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_runtime_token_verifier_requires_owner_claims() -> None:
    exp = datetime.now(timezone.utc) + timedelta(seconds=60)
    token = jwt.encode(
        {
            "actor_kind": "device",
            "actor_id": "device-1",
            "device_id": "device-1",
            "exp": int(exp.timestamp()),
        },
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(RuntimeUnauthenticatedError, match="missing owner_id"):
        await RuntimeTokenVerifier(secret=SECRET).verify(token)
