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
class VerifiedDevice:
    device_id: str
    tenant_id: str
    user_id: str
    default_template_id: str | None
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
    tenant_id: str,
    user_id: str,
    template_id: str | None = None,
    default_template_id: str | None = None,
    scopes: Sequence[str] = ("device",),
    ttl_seconds: int | None = None,
    ttl_days: int | None = None,
) -> tuple[str, datetime]:
    """Return a JWT and its expiration datetime.

    `template_id` is the canonical claim. `default_template_id` and
    `ttl_days` are accepted for compatibility with older pairing-code callers.
    """
    if not secret:
        raise ValueError("sign_device_token: secret is required (empty)")
    if template_id is None:
        template_id = default_template_id

    now = datetime.now(timezone.utc)
    if ttl_seconds is None:
        ttl_seconds = int(
            timedelta(days=ttl_days if ttl_days is not None else 30).total_seconds()
        )
    exp = now + timedelta(seconds=ttl_seconds)
    payload = {
        "device_id": device_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "template_id": template_id,
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


def user_revocation_keys(user_id: str) -> tuple[str, ...]:
    """Return KV keys that revoke every active session for a user."""
    keys = [f"revoked.user.v2.{_kv_safe_token(user_id)}"]
    if _KV_SAFE_RE.fullmatch(user_id):
        keys.append(f"revoked.user.{user_id}")
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

    async def verify(self, token: str) -> VerifiedDevice:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._alg])
        except jwt.PyJWTError as exc:
            raise RuntimeUnauthenticatedError(f"invalid token: {exc}") from exc

        device_id = payload.get("device_id")
        if not device_id:
            raise RuntimeUnauthenticatedError("token missing device_id")
        user_id = payload.get("user_id") or ""

        if self._kv is not None:
            for key in device_revocation_keys(device_id):
                if await self._kv.get(key):
                    raise RuntimeTokenRevokedError(f"device revoked: {device_id}")
            if user_id:
                for key in user_revocation_keys(user_id):
                    if await self._kv.get(key):
                        raise RuntimeTokenRevokedError(
                            f"all sessions revoked for user: {user_id}"
                        )

        return VerifiedDevice(
            device_id=device_id,
            tenant_id=payload.get("tenant_id", ""),
            user_id=user_id,
            default_template_id=payload.get("template_id"),
            scopes=tuple(payload.get("scopes") or ()),
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )


def _kv_safe_token(value: str) -> str:
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")
