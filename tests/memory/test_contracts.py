from __future__ import annotations

import pytest
from pydantic import ValidationError

from eidolon_sdk.memory import (
    KG_PREDICATE_VALUES,
    MEMORY_SCHEMA_VERSION,
    SENSITIVE_PREDICATES,
    ConversationTurnPayload,
    KgAddTripleCommand,
    build_memory_actor_context,
    conversation_turn_subject,
    envelope_memory_payload,
    memory_sync_subject,
    memory_command_subject,
    memory_space_subject_token,
    parse_conversation_turn,
    parse_memory_command,
    unwrap_memory_payload,
)
from eidolon_sdk.memory.subjects import all_memory_stream_patterns


def test_memory_subjects_are_stable() -> None:
    memory_space_id = "default.alice.mochi"
    token = "b64_ZGVmYXVsdC5hbGljZS5tb2NoaQ"
    assert memory_space_subject_token(memory_space_id) == token
    assert "." not in token
    assert conversation_turn_subject(memory_space_id) == (
        f"eidolon.memory.turn.{token}"
    )
    assert memory_command_subject(memory_space_id) == (
        f"eidolon.memory.cmd.{token}"
    )
    assert memory_sync_subject(memory_space_id) == (
        f"eidolon.memory.sync.{token}"
    )
    assert all_memory_stream_patterns() == [
        "eidolon.memory.turn.*",
        "eidolon.memory.cmd.*",
        "eidolon.memory.sync.*",
    ]


def test_memory_subject_memory_space_id_validation() -> None:
    assert conversation_turn_subject("default.user_01.mochi-test") == (
        "eidolon.memory.turn.b64_ZGVmYXVsdC51c2VyXzAxLm1vY2hpLXRlc3Q"
    )
    with pytest.raises(ValueError):
        conversation_turn_subject("bad/user")
    with pytest.raises(ValueError):
        conversation_turn_subject("alice")
    with pytest.raises(ValueError):
        memory_command_subject("")


def _ctx():
    return build_memory_actor_context(
        tenant_id="default",
        owner_user_id="alice",
        companion_id="mochi",
        agent_id="agent-1",
        device_id="device-1",
        instance_id="instance-1",
        session_id="s1",
    )


def test_build_memory_actor_context_maps_companion_to_wire_persona() -> None:
    ctx = _ctx()

    assert ctx.owner_user_id == "alice"
    assert ctx.persona_id == "mochi"
    assert ctx.memory_space_id == "default.alice.mochi"


def test_conversation_turn_payload_serializes_wire_shape() -> None:
    payload = ConversationTurnPayload(
        turn_id="t1",
        context=_ctx(),
        timestamp="2026-06-15T00:00:00Z",
        user_text="hi",
        assistant_text="hello",
        metadata={"source": "test"},
    )

    assert payload.model_dump(mode="json") == {
        "turn_id": "t1",
        "context": {
            "tenant_id": "default",
            "owner_user_id": "alice",
            "persona_id": "mochi",
            "agent_id": "agent-1",
            "device_id": "device-1",
            "instance_id": "instance-1",
            "session_id": "s1",
            "memory_space_id": "default.alice.mochi",
        },
        "timestamp": "2026-06-15T00:00:00Z",
        "user_text": "hi",
        "assistant_text": "hello",
        "metadata": {"source": "test"},
    }


def test_kg_command_predicate_contract() -> None:
    assert "likes" in KG_PREDICATE_VALUES
    assert SENSITIVE_PREDICATES <= set(KG_PREDICATE_VALUES)

    cmd = KgAddTripleCommand(
        request_id="req-1",
        memory_space_id="default.alice.mochi",
        issued_at="2026-06-15T00:00:00Z",
        subject="Alice",
        predicate="likes",
        object="tea",
    )
    assert cmd.kind == "kg_add_triple"

    with pytest.raises(ValidationError):
        KgAddTripleCommand(
            request_id="req-2",
            memory_space_id="default.alice.mochi",
            issued_at="2026-06-15T00:00:00Z",
            subject="Alice",
            predicate="invented_relation",
            object="tea",
        )


def test_memory_envelope_wraps_and_parses_conversation_turn() -> None:
    payload = ConversationTurnPayload(
        turn_id="t1",
        context=_ctx(),
        timestamp="2026-06-15T00:00:00Z",
        user_text="hi",
        assistant_text="hello",
    )

    envelope = envelope_memory_payload(payload, trace_id="trace-1")

    assert envelope.schema_version == MEMORY_SCHEMA_VERSION
    assert envelope.kind == "conversation_turn"
    assert envelope.trace_id == "trace-1"
    assert unwrap_memory_payload(envelope) == payload.model_dump(mode="json")
    assert parse_conversation_turn(envelope) == payload


def test_memory_parsers_accept_raw_current_payloads() -> None:
    raw_turn = {
        "turn_id": "t1",
        "context": _ctx().model_dump(mode="json"),
        "timestamp": "2026-06-15T00:00:00Z",
        "user_text": "hi",
        "assistant_text": "hello",
    }
    raw_command = {
        "kind": "kg_add_triple",
        "request_id": "req-1",
        "memory_space_id": "default.alice.mochi",
        "issued_at": "2026-06-15T00:00:00Z",
        "subject": "Alice",
        "predicate": "likes",
        "object": "tea",
    }

    assert parse_conversation_turn(raw_turn).turn_id == "t1"
    command = parse_memory_command(raw_command)
    assert isinstance(command, KgAddTripleCommand)
    assert command.predicate == "likes"
