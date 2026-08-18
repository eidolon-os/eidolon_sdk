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

    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ttl_seconds)
    payload = {
        "runtime_token_version": 5,
        "owner_id": owner_id,
        "companion_id": companion_id,
        "session_id": session_id,
        "scopes": list(scopes),
        "jti": uuid.uuid4().hex,
        "exp": int(exp.timestamp()),
        "iat": int(now.timestamp()),
    }
    if device_id is not None:
        _require_claim("device_id", device_id)
        payload["device_id"] = device_id
    return jwt.encode(payload, secret, algorithm=algorithm), exp


def device_revocation_keys(device_id: str) -> tuple[str, ...]:
    """Return KV keys that revoke a single device id."""
    return (f"revoked.device.{_kv_safe_token(device_id)}",)


def owner_revocation_keys(owner_id: str) -> tuple[str, ...]:
    """Return KV keys that revoke every active session for an owner."""
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

        if payload.get("runtime_token_version") != 5:
            raise RuntimeUnauthenticatedError("unsupported runtime_token_version")
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

        if self._kv is not None:
            if device_id:
                for key in device_revocation_keys(str(device_id)):
                    if await self._kv.get(key):
                        raise RuntimeTokenRevokedError(f"device revoked: {device_id}")
            for key in owner_revocation_keys(owner_id):
                if await self._kv.get(key):
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
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )


def _require_claim(name: str, value: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"sign_runtime_token: {name} is required")


def _kv_safe_token(value: str) -> str:
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")
