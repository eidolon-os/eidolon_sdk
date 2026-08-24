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
    def __init__(
        self,
        keys: set[str] | None = None,
        *,
        values: dict[str, bytes] | None = None,
    ) -> None:
        self._keys = keys or set()
        #: What the writer actually stores. The owner key holds the instant it
        #: was revoked at, which is what makes it a watermark rather than a
        #: switch; ``keys`` alone keeps the older "any value at all" shape, which
        #: the verifier must still refuse (it cannot read it, so it fails closed).
        self._values = values or {}

    async def get(self, key: str) -> bytes | None:
        if key in self._values:
            return self._values[key]
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


# --- 让所有设备重新登录：a watermark, not a lockout -------------------------


def _mark(moment: datetime) -> bytes:
    """What the Agent writes when an Owner asks to sign every device out."""

    return moment.isoformat().encode("utf-8")


@pytest.mark.asyncio
async def test_a_token_issued_before_the_mark_is_refused() -> None:
    token, _exp = _sign(owner_id="owner-a")
    store = MemoryRevocationStore(
        values={
            owner_revocation_keys("owner-a")[0]: _mark(
                datetime.now(timezone.utc) + timedelta(seconds=5)
            )
        }
    )

    with pytest.raises(RuntimeTokenRevokedError, match="all sessions revoked"):
        await RuntimeTokenVerifier(secret=SECRET, revocation_kv=store).verify(token)


@pytest.mark.asyncio
async def test_a_token_issued_after_the_mark_still_works() -> None:
    """The property that makes the action safe to offer a person.

    Signing every device out has to be something they can do and then keep using
    their Eidolon. Presence-based refusal made it a permanent lockout of the
    whole namespace: every *new* token failed too, and nothing in the product
    deletes the key.
    """

    store = MemoryRevocationStore(
        values={
            owner_revocation_keys("owner-a")[0]: _mark(
                datetime.now(timezone.utc) - timedelta(seconds=5)
            )
        }
    )
    token, _exp = _sign(owner_id="owner-a")

    identity = await RuntimeTokenVerifier(secret=SECRET, revocation_kv=store).verify(token)

    assert identity.owner_id == "owner-a"


@pytest.mark.asyncio
async def test_only_the_named_owner_is_signed_out() -> None:
    store = MemoryRevocationStore(
        values={
            owner_revocation_keys("owner-a")[0]: _mark(
                datetime.now(timezone.utc) + timedelta(seconds=5)
            )
        }
    )
    other, _exp = _sign(owner_id="owner-b")

    identity = await RuntimeTokenVerifier(secret=SECRET, revocation_kv=store).verify(other)

    assert identity.owner_id == "owner-b"


@pytest.mark.asyncio
async def test_a_mark_that_cannot_be_read_refuses_the_token() -> None:
    """Fails closed. "Was this revoked" has one safe answer when the question
    cannot be answered, and a corrupt watermark is exactly that case."""

    for value in (b"revoked", b"", b"not-an-instant"):
        store = MemoryRevocationStore(values={owner_revocation_keys("owner-a")[0]: value})
        token, _exp = _sign(owner_id="owner-a")

        with pytest.raises(RuntimeTokenRevokedError):
            await RuntimeTokenVerifier(secret=SECRET, revocation_kv=store).verify(token)


@pytest.mark.asyncio
async def test_a_naive_mark_is_read_as_utc_rather_than_refused() -> None:
    """Writers store an aware instant; one that lost its offset in transit still
    means a time, and treating it as UTC is what the rest of this product does."""

    store = MemoryRevocationStore(
        values={
            owner_revocation_keys("owner-a")[0]: (
                (datetime.now(timezone.utc) - timedelta(seconds=5))
                .replace(tzinfo=None)
                .isoformat()
                .encode("utf-8")
            )
        }
    )
    token, _exp = _sign(owner_id="owner-a")

    identity = await RuntimeTokenVerifier(secret=SECRET, revocation_kv=store).verify(token)

    assert identity.owner_id == "owner-a"


@pytest.mark.asyncio
async def test_a_device_or_session_key_stays_a_switch() -> None:
    """Deliberately unlike the owner key: a stolen device should stay out until
    something deliberately lets it back in, and "everything until now" is not a
    thing either of these means."""

    later = _mark(datetime.now(timezone.utc) + timedelta(seconds=5))
    earlier = _mark(datetime.now(timezone.utc) - timedelta(seconds=5))
    for key_of, label in (
        (lambda: device_revocation_keys("device-1")[0], "device revoked"),
        (lambda: session_revocation_keys("session-a")[0], "session revoked"),
    ):
        for value in (later, earlier):
            store = MemoryRevocationStore(values={key_of(): value})
            token, _exp = _sign()

            with pytest.raises(RuntimeTokenRevokedError, match=label):
                await RuntimeTokenVerifier(secret=SECRET, revocation_kv=store).verify(token)
