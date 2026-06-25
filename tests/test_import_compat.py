from __future__ import annotations


def test_core_old_paths_reexport_new_objects() -> None:
    from eidolon_sdk.core.http import ServiceHTTPClient as NewHTTPClient
    from eidolon_sdk.core.runtime import BackgroundTaskRunner as NewBackgroundTaskRunner
    from eidolon_sdk.db import SqliteSettings as OldSqliteSettings
    from eidolon_sdk.grpc import GrpcTlsConfig as OldGrpcTlsConfig
    from eidolon_sdk.http import ServiceHTTPClient as OldHTTPClient
    from eidolon_sdk.runtime import BackgroundTaskRunner as OldBackgroundTaskRunner

    from eidolon_sdk.core.db import SqliteSettings as NewSqliteSettings
    from eidolon_sdk.core.grpc import GrpcTlsConfig as NewGrpcTlsConfig

    assert OldHTTPClient is NewHTTPClient
    assert OldGrpcTlsConfig is NewGrpcTlsConfig
    assert OldSqliteSettings is NewSqliteSettings
    assert OldBackgroundTaskRunner is NewBackgroundTaskRunner


def test_business_old_paths_reexport_new_objects() -> None:
    from eidolon_sdk.admin import AdminClient as OldAdminClient
    from eidolon_sdk.biz.admin import AdminClient as NewAdminClient
    from eidolon_sdk.biz.control import build_command_envelope as new_build_command_envelope
    from eidolon_sdk.biz.devices import DeviceAuthHeaders as NewDeviceAuthHeaders
    from eidolon_sdk.biz.long_tasks import session_key_for as new_session_key_for
    from eidolon_sdk.biz.registry import UserRegistryRecord as NewUserRegistryRecord
    from eidolon_sdk.biz.runtime import PairingTokenVerifier as NewPairingTokenVerifier
    from eidolon_sdk.control import build_command_envelope as old_build_command_envelope
    from eidolon_sdk.devices import DeviceAuthHeaders as OldDeviceAuthHeaders
    from eidolon_sdk.long_tasks import session_key_for as old_session_key_for
    from eidolon_sdk.registry import UserRegistryRecord as OldUserRegistryRecord
    from eidolon_sdk.runtime import PairingTokenVerifier as OldPairingTokenVerifier

    assert OldAdminClient is NewAdminClient
    assert OldDeviceAuthHeaders is NewDeviceAuthHeaders
    assert OldUserRegistryRecord is NewUserRegistryRecord
    assert OldPairingTokenVerifier is NewPairingTokenVerifier
    assert old_build_command_envelope is new_build_command_envelope
    assert old_session_key_for is new_session_key_for


def test_integration_old_paths_reexport_new_objects() -> None:
    from eidolon_sdk.integrations.livekit import build_livekit_token as new_livekit_token
    from eidolon_sdk.integrations.llm import (
        render_openai_tool_calls as new_render_openai_tool_calls,
    )
    from eidolon_sdk.livekit import build_livekit_token as old_livekit_token
    from eidolon_sdk.llm import render_openai_tool_calls as old_render_openai_tool_calls

    assert old_livekit_token is new_livekit_token
    assert old_render_openai_tool_calls is new_render_openai_tool_calls


def test_memory_remains_on_legacy_public_path() -> None:
    from eidolon_sdk.memory import ConversationTurnPayload

    assert ConversationTurnPayload.__module__.startswith("eidolon_sdk.memory")
