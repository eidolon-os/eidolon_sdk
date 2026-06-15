"""Small gRPC transport primitives.

This module deliberately avoids importing project protobufs or stubs. It only
owns transport concerns: bearer metadata, token-source resolution, channel
options, and TLS credential materialization.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Literal, TypeAlias


ChannelOption: TypeAlias = tuple[str, int | str]
TokenSource: TypeAlias = str | Callable[[], str | Awaitable[str]]

DEFAULT_LOW_LATENCY_CHANNEL_OPTIONS: tuple[ChannelOption, ...] = (
    ("grpc.optimization_target", "latency"),
    ("grpc.http2.bdp_probe", 1),
)


@dataclass(frozen=True, slots=True)
class GrpcTlsConfig:
    """gRPC client TLS configuration.

    ``mode="off"`` creates an insecure channel. ``mode="tls"`` verifies the
    server certificate. ``mode="mtls"`` additionally sends a client
    certificate and key.
    """

    mode: Literal["off", "tls", "mtls"] | str = "off"
    ca_path: str = ""
    client_cert_path: str = ""
    client_key_path: str = ""


def authorization_metadata(
    token: str,
    *,
    scheme: str = "Bearer",
    header: str = "authorization",
) -> tuple[tuple[str, str], ...]:
    """Return gRPC metadata carrying an authorization token."""
    value = token.strip()
    if not value:
        raise ValueError("authorization token is required")
    scheme = scheme.strip()
    if scheme and not value.lower().startswith(f"{scheme.lower()} "):
        value = f"{scheme} {value}"
    return ((header, value),)


async def resolve_token_source(source: TokenSource) -> str:
    """Resolve a static, sync-callable, or async-callable token source."""
    if isinstance(source, str):
        token = source
    else:
        token_or_awaitable = source()
        if inspect.isawaitable(token_or_awaitable):
            token = await token_or_awaitable
        else:
            token = token_or_awaitable
    if not isinstance(token, str) or not token.strip():
        raise ValueError("token source returned empty/non-string token")
    return token.strip()


def default_channel_options(
    extra: Sequence[ChannelOption] | None = None,
) -> tuple[ChannelOption, ...]:
    """Return default low-latency channel options plus optional extras."""
    if extra is None:
        return DEFAULT_LOW_LATENCY_CHANNEL_OPTIONS
    return (*DEFAULT_LOW_LATENCY_CHANNEL_OPTIONS, *tuple(extra))


def build_channel_credentials(tls: GrpcTlsConfig | None):
    """Return gRPC ChannelCredentials, or ``None`` for insecure channels."""
    if tls is None:
        tls = GrpcTlsConfig()
    if tls.mode == "off":
        return None
    if tls.mode not in ("tls", "mtls"):
        raise ValueError(
            f"REMOTE_AGENT_RPC_TLS_MODE={tls.mode!r} unrecognized; expected "
            "one of: off, tls, mtls"
        )

    import grpc

    ca = _read_optional("ca_path", tls.ca_path) or None
    if tls.mode == "mtls":
        if not tls.client_cert_path or not tls.client_key_path:
            raise ValueError(
                "REMOTE_AGENT_RPC_TLS_MODE=mtls requires "
                "REMOTE_AGENT_RPC_TLS_CLIENT_CERT_PATH and _CLIENT_KEY_PATH"
            )
        return grpc.ssl_channel_credentials(
            root_certificates=ca,
            private_key=_read_required("client_key_path", tls.client_key_path),
            certificate_chain=_read_required("client_cert_path", tls.client_cert_path),
        )
    return grpc.ssl_channel_credentials(root_certificates=ca)


def create_aio_channel(
    target: str,
    *,
    tls: GrpcTlsConfig | None = None,
    options: Sequence[ChannelOption] | None = None,
):
    """Create an async gRPC channel using SDK transport defaults."""
    import grpc

    credentials = build_channel_credentials(tls)
    channel_options = default_channel_options(options)
    if credentials is None:
        return grpc.aio.insecure_channel(target, options=channel_options)
    return grpc.aio.secure_channel(target, credentials, options=channel_options)


def _read_optional(label: str, raw_path: str) -> bytes:
    if not raw_path:
        return b""
    return _read_required(label, raw_path)


def _read_required(label: str, raw_path: str) -> bytes:
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise ValueError(
            f"REMOTE_AGENT_RPC_TLS {label} path does not exist or is not a file: {raw_path}"
        )
    return path.read_bytes()
