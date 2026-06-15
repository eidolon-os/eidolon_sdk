"""gRPC transport helpers shared by Eidolon Python projects."""

from .client import (
    DEFAULT_LOW_LATENCY_CHANNEL_OPTIONS,
    ChannelOption,
    GrpcTlsConfig,
    TokenSource,
    authorization_metadata,
    build_channel_credentials,
    create_aio_channel,
    default_channel_options,
    resolve_token_source,
)

__all__ = [
    "DEFAULT_LOW_LATENCY_CHANNEL_OPTIONS",
    "ChannelOption",
    "GrpcTlsConfig",
    "TokenSource",
    "authorization_metadata",
    "build_channel_credentials",
    "create_aio_channel",
    "default_channel_options",
    "resolve_token_source",
]
