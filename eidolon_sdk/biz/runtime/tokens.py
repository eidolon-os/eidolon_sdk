"""Runtime device JWT contract shared by Eidolon Python projects."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Protocol
import uuid

import jwt

_KV_SAFE_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_SHARED_SECRET_FILE = Path("~/eidolon/run/jwt-secret").expanduser()


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
    actor_kind: str
    actor_id: str
    owner_id: str
    companion_id: str
    device_id: str | None
    memory_realm_id: str
    genome_id: str
    scopes: tuple[str, ...]
    exp: datetime


def resolve_shared_secret(
    env_value: str = "",
    *,
    secret_file: Path | None = None,
) -> str:
    """Resolve the shared HMAC secret from explicit value, then file."""
    val = env_value.strip()
    if val:
        return val
    path = secret_file or _SHARED_SECRET_FILE
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
    actor_kind: str,
    actor_id: str,
    owner_id: str,
    companion_id: str,
    memory_realm_id: str,
    genome_id: str,
    device_id: str | None = None,
    session_id: str | None = None,
    scopes: Sequence[str] = (),
    ttl_seconds: int | None = None,
) -> tuple[str, datetime]:
    """Return a JWT and its expiration datetime."""
    if not secret:
        raise ValueError("sign_runtime_token: secret is required (empty)")
    _require_claim("actor_kind", actor_kind)
    _require_claim("actor_id", actor_id)
    _require_claim("owner_id", owner_id)
    _require_claim("companion_id", companion_id)
    _require_claim("memory_realm_id", memory_realm_id)
    _require_claim("genome_id", genome_id)

    now = datetime.now(timezone.utc)
    if ttl_seconds is None:
        ttl_seconds = int(timedelta(days=30).total_seconds())
    exp = now + timedelta(seconds=ttl_seconds)
    payload = {
        "runtime_token_version": 2,
        "actor_kind": actor_kind,
        "actor_id": actor_id,
        "owner_id": owner_id,
        "companion_id": companion_id,
        "memory_realm_id": memory_realm_id,
        "genome_id": genome_id,
        "scopes": list(scopes),
        "jti": uuid.uuid4().hex,
        "exp": int(exp.timestamp()),
        "iat": int(now.timestamp()),
    }
    if device_id is not None:
        _require_claim("device_id", device_id)
        payload["device_id"] = device_id
    if session_id is not None:
        _require_claim("session_id", session_id)
        payload["session_id"] = session_id
    return jwt.encode(payload, secret, algorithm=algorithm), exp


def sign_device_token(
    *,
    secret: str,
    algorithm: str = "HS256",
    device_id: str,
    owner_id: str,
    companion_id: str,
    memory_realm_id: str,
    genome_id: str,
    scopes: Sequence[str] = ("device",),
    ttl_seconds: int | None = None,
) -> tuple[str, datetime]:
    """Return a device-origin runtime JWT.

    Kept as the public compatibility wrapper for existing ESP32/admin-test
    callers. New non-device entrances should call ``sign_runtime_token`` and
    choose their actor kind explicitly.
    """
    try:
        return sign_runtime_token(
            secret=secret,
            algorithm=algorithm,
            actor_kind="device",
            actor_id=device_id,
            device_id=device_id,
            owner_id=owner_id,
            companion_id=companion_id,
            memory_realm_id=memory_realm_id,
            genome_id=genome_id,
            scopes=scopes,
            ttl_seconds=ttl_seconds,
        )
    except ValueError as exc:
        raise ValueError(str(exc).replace("sign_runtime_token", "sign_device_token")) from exc


def device_revocation_keys(device_id: str) -> tuple[str, ...]:
    """Return KV keys that revoke a single device id."""
    keys = [f"revoked.device.{_kv_safe_token(device_id)}"]
    if _KV_SAFE_RE.fullmatch(device_id):
        keys.append(f"revoked.{device_id}")
    return tuple(keys)


def owner_revocation_keys(owner_id: str) -> tuple[str, ...]:
    """Return KV keys that revoke every active session for an owner."""
    keys = [f"revoked.owner.{_kv_safe_token(owner_id)}"]
    if _KV_SAFE_RE.fullmatch(owner_id):
        keys.append(f"revoked.owner.{owner_id}")
    return tuple(keys)


def session_revocation_keys(session_id: str) -> tuple[str, ...]:
    """Return KV keys that revoke one runtime session."""
    keys = [f"revoked.session.{_kv_safe_token(session_id)}"]
    if _KV_SAFE_RE.fullmatch(session_id):
        keys.append(f"revoked.session.{session_id}")
    return tuple(keys)


def jti_revocation_keys(jti: str) -> tuple[str, ...]:
    """Return KV keys that revoke one concrete JWT id."""
    keys = [f"revoked.jti.{_kv_safe_token(jti)}"]
    if _KV_SAFE_RE.fullmatch(jti):
        keys.append(f"revoked.jti.{jti}")
    return tuple(keys)


class RuntimeTokenVerifier:
    def __init__(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        revocation_kv: RuntimeRevocationStore | None = None,
    ) -> None:
        if not secret:
            raise ValueError("RuntimeTokenVerifier: secret is required (empty)")
        self._secret = secret
        self._alg = algorithm
        self._kv = revocation_kv

    async def verify(self, token: str) -> RuntimeIdentity:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._alg])
        except jwt.PyJWTError as exc:
            raise RuntimeUnauthenticatedError(f"invalid token: {exc}") from exc

        device_id = payload.get("device_id")
        actor_kind = str(payload.get("actor_kind") or "").strip()
        actor_id = str(payload.get("actor_id") or "").strip()
        if not actor_kind or not actor_id:
            if not device_id:
                raise RuntimeUnauthenticatedError(
                    "token missing actor_kind/actor_id or legacy device_id"
                )
            actor_kind = "device"
            actor_id = str(device_id)
        owner_id = payload.get("owner_id") or ""
        companion_id = payload.get("companion_id") or ""
        memory_realm_id = payload.get("memory_realm_id") or ""
        genome_id = payload.get("genome_id") or ""
        for claim_name, claim_value in (
            ("owner_id", owner_id),
            ("companion_id", companion_id),
            ("memory_realm_id", memory_realm_id),
            ("genome_id", genome_id),
        ):
            if not claim_value:
                raise RuntimeUnauthenticatedError(f"token missing {claim_name}")

        if self._kv is not None:
            if device_id:
                for key in device_revocation_keys(str(device_id)):
                    if await self._kv.get(key):
                        raise RuntimeTokenRevokedError(f"device revoked: {device_id}")
            for key in owner_revocation_keys(owner_id):
                if await self._kv.get(key):
                    raise RuntimeTokenRevokedError(
                        f"all sessions revoked for owner: {owner_id}"
                    )
            session_id = str(payload.get("session_id") or "").strip()
            if session_id:
                for key in session_revocation_keys(session_id):
                    if await self._kv.get(key):
                        raise RuntimeTokenRevokedError(
                            f"session revoked: {session_id}"
                        )
            jti = str(payload.get("jti") or "").strip()
            if jti:
                for key in jti_revocation_keys(jti):
                    if await self._kv.get(key):
                        raise RuntimeTokenRevokedError(f"token revoked: {jti}")

        return RuntimeIdentity(
            actor_kind=actor_kind,
            actor_id=actor_id,
            device_id=str(device_id) if device_id else None,
            owner_id=owner_id,
            companion_id=companion_id,
            memory_realm_id=memory_realm_id,
            genome_id=genome_id,
            scopes=tuple(payload.get("scopes") or ()),
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )


def _require_claim(name: str, value: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"sign_runtime_token: {name} is required")


def _kv_safe_token(value: str) -> str:
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")
