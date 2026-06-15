from __future__ import annotations

import pytest

from eidolon_sdk.grpc import (
    DEFAULT_LOW_LATENCY_CHANNEL_OPTIONS,
    GrpcTlsConfig,
    authorization_metadata,
    build_channel_credentials,
    default_channel_options,
    resolve_token_source,
)


def test_authorization_metadata_builds_bearer_header() -> None:
    assert authorization_metadata("abc") == (("authorization", "Bearer abc"),)
    assert authorization_metadata("Bearer abc") == (("authorization", "Bearer abc"),)


def test_authorization_metadata_rejects_empty_token() -> None:
    with pytest.raises(ValueError, match="token"):
        authorization_metadata(" ")


@pytest.mark.asyncio
async def test_resolve_token_source_accepts_static_sync_and_async() -> None:
    async def async_token() -> str:
        return "async-token"

    assert await resolve_token_source("static") == "static"
    assert await resolve_token_source(lambda: "sync-token") == "sync-token"
    assert await resolve_token_source(async_token) == "async-token"


@pytest.mark.asyncio
async def test_resolve_token_source_rejects_empty_or_non_string() -> None:
    with pytest.raises(ValueError, match="empty/non-string"):
        await resolve_token_source(lambda: "")
    with pytest.raises(ValueError, match="empty/non-string"):
        await resolve_token_source(lambda: 123)  # type: ignore[return-value]


def test_default_channel_options_include_latency_hints_without_keepalive() -> None:
    options = default_channel_options(extra=(("grpc.max_receive_message_length", 1),))
    names = {name for name, _ in options}

    assert DEFAULT_LOW_LATENCY_CHANNEL_OPTIONS[0] in options
    assert "grpc.http2.bdp_probe" in names
    assert "grpc.max_receive_message_length" in names
    assert "grpc.keepalive_time_ms" not in names
    assert "grpc.keepalive_permit_without_calls" not in names
    assert "grpc.http2.max_pings_without_data" not in names


def test_build_channel_credentials_returns_none_for_tls_off() -> None:
    assert build_channel_credentials(GrpcTlsConfig(mode="off")) is None


def test_build_channel_credentials_validates_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        build_channel_credentials(GrpcTlsConfig(mode="please-no"))


def test_build_channel_credentials_validates_mtls_paths() -> None:
    with pytest.raises(ValueError, match="mtls"):
        build_channel_credentials(GrpcTlsConfig(mode="mtls"))


def test_build_channel_credentials_validates_ca_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="ca_path"):
        build_channel_credentials(
            GrpcTlsConfig(mode="tls", ca_path=str(tmp_path / "nope.pem"))
        )
