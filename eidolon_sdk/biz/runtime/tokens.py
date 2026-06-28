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
    owner_id: str
    companion_id: str
    device_id: str
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
    """Return a JWT and its expiration datetime."""
    if not secret:
        raise ValueError("sign_device_token: secret is required (empty)")
    _require_claim("device_id", device_id)
    _require_claim("owner_id", owner_id)
    _require_claim("companion_id", companion_id)
    _require_claim("memory_realm_id", memory_realm_id)
    _require_claim("genome_id", genome_id)

    now = datetime.now(timezone.utc)
    if ttl_seconds is None:
        ttl_seconds = int(timedelta(days=30).total_seconds())
    exp = now + timedelta(seconds=ttl_seconds)
    payload = {
        "device_id": device_id,
        "owner_id": owner_id,
        "companion_id": companion_id,
        "memory_realm_id": memory_realm_id,
        "genome_id": genome_id,
        "scopes": list(scopes),
        "jti": uuid.uuid4().hex,
        "exp": int(exp.timestamp()),
        "iat": int(now.timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=algorithm), exp


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


class PairingTokenVerifier:
    def __init__(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        revocation_kv: RuntimeRevocationStore | None = None,
    ) -> None:
        if not secret:
            raise ValueError("PairingTokenVerifier: secret is required (empty)")
        self._secret = secret
        self._alg = algorithm
        self._kv = revocation_kv

    async def verify(self, token: str) -> RuntimeIdentity:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._alg])
        except jwt.PyJWTError as exc:
            raise RuntimeUnauthenticatedError(f"invalid token: {exc}") from exc

        device_id = payload.get("device_id")
        if not device_id:
            raise RuntimeUnauthenticatedError("token missing device_id")
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
            for key in device_revocation_keys(device_id):
                if await self._kv.get(key):
                    raise RuntimeTokenRevokedError(f"device revoked: {device_id}")
            for key in owner_revocation_keys(owner_id):
                if await self._kv.get(key):
                    raise RuntimeTokenRevokedError(
                        f"all sessions revoked for owner: {owner_id}"
                    )

        return RuntimeIdentity(
            device_id=device_id,
            owner_id=owner_id,
            companion_id=companion_id,
            memory_realm_id=memory_realm_id,
            genome_id=genome_id,
            scopes=tuple(payload.get("scopes") or ()),
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )


def _require_claim(name: str, value: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"sign_device_token: {name} is required")


def _kv_safe_token(value: str) -> str:
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")
