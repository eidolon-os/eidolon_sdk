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
        device_id=device_id,
        owner_id=kwargs.pop("owner_id", "owner-a"),
        companion_id=kwargs.pop("companion_id", "companion-a"),
        session_id=kwargs.pop("session_id", "session-a"),
        ttl_seconds=kwargs.pop("ttl_seconds", 60),
        **kwargs,
    )


def test_sign_runtime_token_carries_only_session_principal_and_target() -> None:
    token, exp = _sign(
        device_id="web-123",
        owner_id="owner-a",
        companion_id="companion-a",
        scopes=("device", "voice"),
        ttl_seconds=60,
    )

    payload = jwt.decode(token, SECRET, algorithms=["HS256"])

    assert payload["device_id"] == "web-123"
    assert payload["runtime_token_version"] == 5
    assert "actor_kind" not in payload
    assert "actor_id" not in payload
    assert payload["owner_id"] == "owner-a"
    assert payload["companion_id"] == "companion-a"
    assert payload["session_id"] == "session-a"
    assert "memory_realm_id" not in payload
    assert "genome_id" not in payload
    assert "schema_version" not in payload
    assert "genome_hash" not in payload
    assert "realizer_version" not in payload
    assert payload["scopes"] == ["device", "voice"]
    assert isinstance(payload["jti"], str)
    assert datetime.fromtimestamp(payload["exp"], tz=timezone.utc) == exp.replace(microsecond=0)
    assert payload["iat"] <= payload["exp"]


def test_sign_runtime_token_rejects_empty_secret() -> None:
    with pytest.raises(ValueError, match="secret is required"):
        sign_runtime_token(
            secret="",
            device_id="device-1",
            owner_id="owner-a",
            companion_id="companion-a",
            session_id="session-a",
            ttl_seconds=60,
        )


def test_sign_runtime_token_requires_identity_claims() -> None:
    with pytest.raises(ValueError, match="owner_id is required"):
        _sign(owner_id="")


@pytest.mark.parametrize("ttl_seconds", [0, -1, True, 1.5])
def test_sign_runtime_token_requires_positive_integer_ttl(ttl_seconds: object) -> None:
    with pytest.raises(ValueError, match="ttl_seconds must be a positive integer"):
        _sign(ttl_seconds=ttl_seconds)


def test_runtime_token_verifier_rejects_empty_secret() -> None:
    with pytest.raises(ValueError, match="secret is required"):
        RuntimeTokenVerifier(secret="")


@pytest.mark.asyncio
async def test_runtime_token_verifier_round_trips_runtime_identity() -> None:
    token, exp = _sign(scopes=("device",), session_id="session-1", ttl_seconds=60)

    verified = await RuntimeTokenVerifier(secret=SECRET).verify(token)

    assert verified.device_id == "device-1"
    assert verified.session_id == "session-1"
    assert verified.owner_id == "owner-a"
    assert verified.companion_id == "companion-a"
    assert verified.scopes == ("device",)
    assert verified.exp == exp.replace(microsecond=0)


@pytest.mark.asyncio
async def test_runtime_token_verifier_rejects_wrong_secret() -> None:
    token, _exp = _sign()

    with pytest.raises(RuntimeUnauthenticatedError, match="invalid token"):
        await RuntimeTokenVerifier(secret="wrong-secret-with-enough-bytes-32").verify(token)


@pytest.mark.asyncio
async def test_runtime_token_verifier_rejects_expired_token() -> None:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "runtime_token_version": 5,
            "owner_id": "owner-a",
            "companion_id": "companion-a",
            "session_id": "session-a",
            "exp": int((now - timedelta(seconds=1)).timestamp()),
        },
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(RuntimeUnauthenticatedError, match="expired"):
        await RuntimeTokenVerifier(secret=SECRET).verify(token)


@pytest.mark.asyncio
async def test_runtime_token_verifier_checks_device_and_owner_revocations() -> None:
    device_token, _exp = _sign(device_id="1c:db:a1")
    device_store = MemoryRevocationStore({device_revocation_keys("1c:db:a1")[0]})

    with pytest.raises(RuntimeTokenRevokedError, match="device revoked"):
        await RuntimeTokenVerifier(secret=SECRET, revocation_kv=device_store).verify(device_token)

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
async def test_runtime_token_verifier_accepts_owner_without_device_id() -> None:
    token, exp = sign_runtime_token(
        secret=SECRET,
        owner_id="owner-a",
        companion_id="companion-a",
        session_id="web-session-1",
        scopes=("web",),
        ttl_seconds=60,
    )

    verified = await RuntimeTokenVerifier(secret=SECRET).verify(token)

    assert verified.device_id is None
    assert verified.owner_id == "owner-a"
    assert verified.companion_id == "companion-a"
    assert verified.scopes == ("web",)
    assert verified.exp == exp.replace(microsecond=0)


@pytest.mark.asyncio
async def test_runtime_token_verifier_rejects_obsolete_token_version() -> None:
    exp = datetime.now(timezone.utc) + timedelta(seconds=60)
    token = jwt.encode(
        {"runtime_token_version": 3, "exp": int(exp.timestamp())},
        SECRET,
        algorithm="HS256",
    )

    verifier = RuntimeTokenVerifier(secret=SECRET)

    with pytest.raises(RuntimeUnauthenticatedError, match="runtime_token_version"):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_runtime_token_verifier_requires_owner_claims() -> None:
    exp = datetime.now(timezone.utc) + timedelta(seconds=60)
    token = jwt.encode(
        {
            "runtime_token_version": 5,
            "device_id": "device-1",
            "exp": int(exp.timestamp()),
        },
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(RuntimeUnauthenticatedError, match="missing owner_id"):
        await RuntimeTokenVerifier(secret=SECRET).verify(token)


@pytest.mark.asyncio
async def test_runtime_token_verifier_requires_session_claim() -> None:
    exp = datetime.now(timezone.utc) + timedelta(seconds=60)
    token = jwt.encode(
        {
            "runtime_token_version": 5,
            "owner_id": "owner-a",
            "companion_id": "companion-a",
            "exp": int(exp.timestamp()),
        },
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(RuntimeUnauthenticatedError, match="missing session_id"):
        await RuntimeTokenVerifier(secret=SECRET).verify(token)
