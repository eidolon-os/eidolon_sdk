"""Owner-scoped Agent runtime JWT contract shared by Eidolon Python projects."""

from __future__ import annotations

import base64
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
import uuid

import jwt



def _shared_secret_file() -> Path:
    runtime_root = Path(
        os.environ.get("EIDOLON_RUNTIME_ROOT", "~/eidolon/run")
    ).expanduser()
    return runtime_root / "agent/jwt-secret"


class RuntimeUnauthenticatedError(ValueError):
    """Raised when a runtime JWT cannot be authenticated."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RuntimeTokenRevokedError(RuntimeUnauthenticatedError):
    """Raised when a valid runtime JWT is present in the revocation store."""


class RuntimeRevocationStore(Protocol):
    async def get(self, key: str) -> bytes | str | None: ...


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    """Authenticated Owner scope and selected Companion for one client session.

    System Data runtime facts are deliberately absent. The Agent resolves and
    pins those facts from the Companion Runtime Authority after authentication.
    """

    owner_id: str
    companion_id: str
    device_id: str | None
    session_id: str
    scopes: tuple[str, ...]
    exp: datetime
    person_id: str | None = None
    source_session_id: str | None = None
    person_revision: int | None = None
    identity_epoch: int | None = None
    memory_mode: str = "personal"


def resolve_shared_secret(
    env_value: str = "",
    *,
    secret_file: Path | None = None,
) -> str:
    """Resolve the shared HMAC secret from explicit value, then file."""
    val = env_value.strip()
    if val:
        return val
    path = secret_file or _shared_secret_file()
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def sign_runtime_token(
    *,
    secret: str,
    algorithm: str = "HS256",
    owner_id: str,
    companion_id: str,
    session_id: str,
    device_id: str | None = None,
    scopes: Sequence[str] = (),
    person_id: str | None = None,
    source_session_id: str | None = None,
    person_revision: int | None = None,
    identity_epoch: int | None = None,
    memory_mode: str = "personal",
    ttl_seconds: int,
) -> tuple[str, datetime]:
    """Return a JWT and its expiration datetime using an explicit caller TTL."""
    if not secret:
        raise ValueError("sign_runtime_token: secret is required (empty)")
    _require_claim("owner_id", owner_id)
    _require_claim("companion_id", companion_id)
    _require_claim("session_id", session_id)
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        raise ValueError("sign_runtime_token: ttl_seconds must be a positive integer")

    _validate_person_binding(person_id, identity_epoch, person_revision)
    _validate_memory_mode(memory_mode, person_id, source_session_id, session_id)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ttl_seconds)
    payload = {
        "runtime_token_version": 8 if memory_mode == "provisional" else 7,
        "owner_id": owner_id,
        "companion_id": companion_id,
        "session_id": session_id,
        "scopes": list(scopes),
        "jti": uuid.uuid4().hex,
        "exp": int(exp.timestamp()),
        "iat": int(now.timestamp()),
    }
    if memory_mode == "provisional":
        payload["memory_mode"] = memory_mode
    if source_session_id is not None:
        _validate_source_session(source_session_id)
        payload["source_session_id"] = source_session_id
    if person_id is not None:
        payload.update(person_id=person_id, identity_epoch=identity_epoch, person_revision=person_revision)
    if device_id is not None:
        _require_claim("device_id", device_id)
        payload["device_id"] = device_id
    return jwt.encode(payload, secret, algorithm=algorithm), exp


def device_revocation_keys(device_id: str) -> tuple[str, ...]:
    """Return KV keys that revoke a single device id."""
    return (f"revoked.device.{_kv_safe_token(device_id)}",)


def owner_revocation_keys(owner_id: str) -> tuple[str, ...]:
    """Return KV keys that revoke every session an owner had **until now**.

    A watermark, not a switch, and that difference is the whole point of the key.
    The writer stores the instant it revoked at; a token is refused when it was
    issued before that instant, and a token issued after it is fine. So "sign
    every device out" is something a person can ask for and then keep using
    their Eidolon — the devices reconnect on their own.

    Presence alone used to be enough to refuse, which made this a permanent
    lockout of an Owner's whole namespace: every *new* token failed too, nothing
    in the product deletes the key, and the value the writer stored — already an
    ISO instant — was never read. A management surface offering that as "让所有
    设备重新登录" would have bricked every device an Owner has.

    Deliberately unlike :func:`device_revocation_keys` and
    :func:`session_revocation_keys`, which stay presence-based: a stolen device
    or a poisoned session should stay out until something deliberately lets it
    back in, and there is no "everything until now" in either.
    """

    return (f"revoked.owner.{_kv_safe_token(owner_id)}",)


def session_revocation_keys(session_id: str) -> tuple[str, ...]:
    """Return KV keys that revoke one runtime session."""
    return (f"revoked.session.{_kv_safe_token(session_id)}",)


def jti_revocation_keys(jti: str) -> tuple[str, ...]:
    """Return KV keys that revoke one concrete JWT id."""
    return (f"revoked.jti.{_kv_safe_token(jti)}",)


class RuntimeTokenVerifier:
    def __init__(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        revocation_kv: RuntimeRevocationStore | None = None,
        allow_provisional: bool = False,
    ) -> None:
        if not secret:
            raise ValueError("RuntimeTokenVerifier: secret is required (empty)")
        self._secret = secret
        self._alg = algorithm
        self._kv = revocation_kv
        self._allow_provisional = allow_provisional

    async def verify(self, token: str) -> RuntimeIdentity:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._alg])
        except jwt.PyJWTError as exc:
            raise RuntimeUnauthenticatedError(f"invalid token: {exc}") from exc

        if type(payload.get("runtime_token_version")) is not int or payload["runtime_token_version"] not in (7, 8):
            raise RuntimeUnauthenticatedError("unsupported runtime_token_version")
        version = payload["runtime_token_version"]
        if version == 8 and not self._allow_provisional:
            raise RuntimeUnauthenticatedError("provisional runtime is not supported by this consumer")
        memory_mode = payload.get("memory_mode", "personal")
        if ((version == 7 and "memory_mode" in payload)
                or (version == 8 and memory_mode != "provisional")):
            raise RuntimeUnauthenticatedError("memory mode does not match token version")
        person_id = payload.get("person_id")
        identity_epoch = payload.get("identity_epoch")
        person_revision = payload.get("person_revision")
        try:
            _validate_person_binding(person_id, identity_epoch, person_revision)
        except ValueError as exc:
            raise RuntimeUnauthenticatedError(str(exc)) from exc
        if person_id is None and ("person_id" in payload or "identity_epoch" in payload or "person_revision" in payload):
            raise RuntimeUnauthenticatedError("personal identity claims cannot be null")
        source_session_id = payload.get("source_session_id")
        if source_session_id is not None:
            try:
                _validate_source_session(source_session_id)
            except ValueError as exc:
                raise RuntimeUnauthenticatedError(str(exc)) from exc
        device_id = payload.get("device_id")
        owner_id = payload.get("owner_id") or ""
        companion_id = payload.get("companion_id") or ""
        session_id = str(payload.get("session_id") or "").strip()
        for claim_name, claim_value in (
            ("owner_id", owner_id),
            ("companion_id", companion_id),
            ("session_id", session_id),
        ):
            if not claim_value:
                raise RuntimeUnauthenticatedError(f"token missing {claim_name}")

        try:
            _validate_memory_mode(memory_mode, person_id, source_session_id, session_id)
        except ValueError as exc:
            raise RuntimeUnauthenticatedError(str(exc)) from exc

        if self._kv is not None:
            if device_id:
                for key in device_revocation_keys(str(device_id)):
                    if await self._kv.get(key):
                        raise RuntimeTokenRevokedError(f"device revoked: {device_id}")
            for key in owner_revocation_keys(owner_id):
                mark = await self._kv.get(key)
                if mark is not None and _issued_before(payload, mark):
                    raise RuntimeTokenRevokedError(f"all sessions revoked for owner: {owner_id}")
            for key in session_revocation_keys(session_id):
                if await self._kv.get(key):
                    raise RuntimeTokenRevokedError(f"session revoked: {session_id}")
            jti = str(payload.get("jti") or "").strip()
            if jti:
                for key in jti_revocation_keys(jti):
                    if await self._kv.get(key):
                        raise RuntimeTokenRevokedError(f"token revoked: {jti}")

        return RuntimeIdentity(
            device_id=str(device_id) if device_id else None,
            session_id=session_id,
            owner_id=owner_id,
            companion_id=companion_id,
            scopes=tuple(payload.get("scopes") or ()),
            person_id=person_id,
            identity_epoch=identity_epoch,
            person_revision=person_revision,
            source_session_id=source_session_id,
            memory_mode=memory_mode,
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )


def _issued_before(payload: dict, mark: bytes) -> bool:
    """Whether this token predates the watermark stored for its owner.

    Fails closed on anything it cannot read. A mark that is not an instant, or a
    token with no ``iat``, means the question cannot be answered — and the safe
    answer to "was this revoked" is yes. Runtime tokens always carry ``iat``,
    so the second case is a token from somewhere else.
    """

    try:
        revoked_at = datetime.fromisoformat(mark.decode("utf-8").strip())
    except (UnicodeDecodeError, ValueError):
        return True
    if revoked_at.tzinfo is None:
        revoked_at = revoked_at.replace(tzinfo=timezone.utc)
    issued_at = payload.get("iat")
    if not isinstance(issued_at, int | float):
        return True
    return datetime.fromtimestamp(float(issued_at), tz=timezone.utc) < revoked_at


def _require_claim(name: str, value: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"sign_runtime_token: {name} is required")


def _kv_safe_token(value: str) -> str:
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _validate_person_binding(person_id, identity_epoch, person_revision):
    if person_id is None and identity_epoch is None and person_revision is None:
        return
    if (not isinstance(person_id, str) or not person_id.strip()
            or person_id != person_id.strip() or len(person_id) > 64):
        raise ValueError("personal runtime requires a valid person_id")
    if type(person_revision) is not int or person_revision < 1:
        raise ValueError("personal runtime requires a positive person_revision")
    if type(identity_epoch) is not int or identity_epoch < 0:
        raise ValueError("personal runtime requires a non-negative identity_epoch")


def _validate_source_session(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
        raise ValueError("source_session_id must be a canonical nonempty string")


def _validate_memory_mode(mode, person_id, source_session_id, session_id):
    if mode not in ("personal", "provisional"):
        raise ValueError("invalid runtime memory mode")
    if mode == "provisional" and (person_id is None or source_session_id != session_id):
        raise ValueError("provisional runtime requires a Person bound to the source session")
