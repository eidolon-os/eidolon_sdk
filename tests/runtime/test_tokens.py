from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from eidolon_sdk.biz.runtime import (
    PairingTokenVerifier,
    RuntimeTokenRevokedError,
    RuntimeUnauthenticatedError,
    device_revocation_keys,
    resolve_shared_secret,
    sign_device_token,
    user_revocation_keys,
)


SECRET = "test-secret-with-enough-entropy-32b"


class MemoryRevocationStore:
    def __init__(self, keys: set[str] | None = None) -> None:
        self._keys = keys or set()

    async def get(self, key: str) -> bytes | None:
        return b"revoked" if key in self._keys else None


def test_sign_device_token_pins_payload_schema() -> None:
    token, exp = sign_device_token(
        secret=SECRET,
        device_id="web-123",
        tenant_id="tenant-a",
        user_id="user-a",
        template_id="template-a",
        scopes=("device", "voice"),
        ttl_seconds=60,
    )

    payload = jwt.decode(token, SECRET, algorithms=["HS256"])

    assert payload["device_id"] == "web-123"
    assert payload["tenant_id"] == "tenant-a"
    assert payload["user_id"] == "user-a"
    assert payload["template_id"] == "template-a"
    assert payload["scopes"] == ["device", "voice"]
    assert isinstance(payload["jti"], str)
    assert datetime.fromtimestamp(payload["exp"], tz=timezone.utc) == exp.replace(microsecond=0)
    assert payload["iat"] <= payload["exp"]


def test_sign_device_token_supports_legacy_agent_arguments() -> None:
    token, _exp = sign_device_token(
        secret=SECRET,
        device_id="device-1",
        tenant_id="tenant-a",
        user_id="user-a",
        default_template_id="legacy-template",
        scopes=["device"],
        ttl_days=1,
    )

    payload = jwt.decode(token, SECRET, algorithms=["HS256"])

    assert payload["template_id"] == "legacy-template"
    assert payload["exp"] - payload["iat"] == 24 * 3600


def test_sign_device_token_rejects_empty_secret() -> None:
    with pytest.raises(ValueError, match="secret is required"):
        sign_device_token(
            secret="",
            device_id="device-1",
            tenant_id="tenant-a",
            user_id="user-a",
            template_id=None,
        )


def test_pairing_token_verifier_rejects_empty_secret() -> None:
    with pytest.raises(ValueError, match="secret is required"):
        PairingTokenVerifier(secret="")


@pytest.mark.asyncio
async def test_pairing_token_verifier_round_trips_verified_device() -> None:
    token, exp = sign_device_token(
        secret=SECRET,
        device_id="device-1",
        tenant_id="tenant-a",
        user_id="user-a",
        template_id="template-a",
        scopes=("device",),
        ttl_seconds=60,
    )

    verified = await PairingTokenVerifier(secret=SECRET).verify(token)

    assert verified.device_id == "device-1"
    assert verified.tenant_id == "tenant-a"
    assert verified.user_id == "user-a"
    assert verified.default_template_id == "template-a"
    assert verified.scopes == ("device",)
    assert verified.exp == exp.replace(microsecond=0)


@pytest.mark.asyncio
async def test_pairing_token_verifier_rejects_wrong_secret() -> None:
    token, _exp = sign_device_token(
        secret=SECRET,
        device_id="device-1",
        tenant_id="tenant-a",
        user_id="user-a",
        template_id=None,
    )

    with pytest.raises(RuntimeUnauthenticatedError, match="invalid token"):
        await PairingTokenVerifier(secret="wrong-secret-with-enough-bytes-32").verify(token)


@pytest.mark.asyncio
async def test_pairing_token_verifier_rejects_expired_token() -> None:
    token, _exp = sign_device_token(
        secret=SECRET,
        device_id="device-1",
        tenant_id="tenant-a",
        user_id="user-a",
        template_id=None,
        ttl_seconds=-1,
    )

    with pytest.raises(RuntimeUnauthenticatedError, match="expired"):
        await PairingTokenVerifier(secret=SECRET).verify(token)


@pytest.mark.asyncio
async def test_pairing_token_verifier_checks_device_and_user_revocations() -> None:
    device_token, _exp = sign_device_token(
        secret=SECRET,
        device_id="1c:db:a1",
        tenant_id="tenant-a",
        user_id="user-a",
        template_id=None,
    )
    device_store = MemoryRevocationStore({device_revocation_keys("1c:db:a1")[0]})

    with pytest.raises(RuntimeTokenRevokedError, match="device revoked"):
        await PairingTokenVerifier(secret=SECRET, revocation_kv=device_store).verify(
            device_token
        )

    user_token, _exp = sign_device_token(
        secret=SECRET,
        device_id="device-1",
        tenant_id="tenant-a",
        user_id="user-a",
        template_id=None,
    )
    user_store = MemoryRevocationStore({user_revocation_keys("user-a")[0]})

    with pytest.raises(RuntimeTokenRevokedError, match="all sessions revoked"):
        await PairingTokenVerifier(secret=SECRET, revocation_kv=user_store).verify(user_token)


def test_revocation_keys_include_legacy_key_only_for_kv_safe_ids() -> None:
    assert device_revocation_keys("device-1") == (
        "revoked.device.ZGV2aWNlLTE",
        "revoked.device-1",
    )
    assert device_revocation_keys("1c:db:a1") == ("revoked.device.MWM6ZGI6YTE",)
    assert user_revocation_keys("user-a") == (
        "revoked.user.v2.dXNlci1h",
        "revoked.user.user-a",
    )


def test_resolve_shared_secret_prefers_argument_then_file(tmp_path) -> None:
    secret_file = tmp_path / "jwt-secret"
    secret_file.write_text(" from-file \n", encoding="utf-8")

    assert resolve_shared_secret(" from-arg ", secret_file=secret_file) == "from-arg"
    assert resolve_shared_secret("", secret_file=secret_file) == "from-file"
    assert resolve_shared_secret("", secret_file=tmp_path / "missing") == ""


@pytest.mark.asyncio
async def test_pairing_token_verifier_requires_device_id() -> None:
    exp = datetime.now(timezone.utc) + timedelta(seconds=60)
    token = jwt.encode({"exp": int(exp.timestamp())}, SECRET, algorithm="HS256")

    verifier = PairingTokenVerifier(secret=SECRET)

    with pytest.raises(RuntimeUnauthenticatedError, match="missing device_id"):
        await verifier.verify(token)
