from __future__ import annotations

import pytest
from pydantic import ValidationError

from eidolon_sdk.memory import (
    KG_PREDICATE_VALUES,
    SENSITIVE_PREDICATES,
    ConversationTurnPayload,
    KgAddTripleCommand,
    conversation_turn_subject,
    memory_command_subject,
)
from eidolon_sdk.memory.subjects import all_memory_stream_patterns


def test_memory_subjects_are_stable() -> None:
    assert conversation_turn_subject("alice") == "agent.memory.conversation.turn.alice"
    assert memory_command_subject("alice") == "agent.memory.cmd.alice"
    assert all_memory_stream_patterns() == [
        "agent.memory.conversation.turn.>",
        "agent.memory.cmd.>",
    ]


def test_memory_subject_user_id_validation() -> None:
    assert conversation_turn_subject("user.01") == "agent.memory.conversation.turn.user.01"
    with pytest.raises(ValueError):
        conversation_turn_subject("bad/user")
    with pytest.raises(ValueError):
        memory_command_subject("")


def test_conversation_turn_payload_serializes_wire_shape() -> None:
    payload = ConversationTurnPayload(
        turn_id="t1",
        user_id="alice",
        session_id="s1",
        timestamp="2026-06-15T00:00:00Z",
        user_text="hi",
        assistant_text="hello",
        metadata={"source": "test"},
    )

    assert payload.model_dump(mode="json") == {
        "turn_id": "t1",
        "user_id": "alice",
        "session_id": "s1",
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
        user_id="alice",
        issued_at="2026-06-15T00:00:00Z",
        subject="Alice",
        predicate="likes",
        object="tea",
    )
    assert cmd.kind == "kg_add_triple"

    with pytest.raises(ValidationError):
        KgAddTripleCommand(
            request_id="req-2",
            user_id="alice",
            issued_at="2026-06-15T00:00:00Z",
            subject="Alice",
            predicate="invented_relation",
            object="tea",
        )
