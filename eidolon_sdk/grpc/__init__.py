"""Compatibility exports for :mod:`eidolon_sdk.core.grpc`."""

from eidolon_sdk.core.grpc import (
    DEFAULT_LOW_LATENCY_CHANNEL_OPTIONS,
    ChannelOption,
    GrpcTlsConfig,
    TokenSource,
    authorization_metadata,
    build_channel_credentials,
    create_aio_channel,
    create_aio_channel_with_credentials,
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
    "create_aio_channel_with_credentials",
    "default_channel_options",
    "resolve_token_source",
]
