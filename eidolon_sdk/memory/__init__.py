"""Memory service wire contracts shared across Eidolon projects."""

from .kg import (
    KG_PREDICATE_VALUES,
    SENSITIVE_PREDICATES,
    USER_CONFIRMED_ROOM_PREFIX,
    ConsolidatorIngestThemeCommand,
    KgAddTripleCommand,
    KgInvalidateCommand,
    KgPredicate,
    MemoryCommandPayload,
    UserConfirmedFactCommand,
)
from .payloads import ConversationTurnPayload
from .subjects import (
    MEMORY_COMMAND_BASE,
    MEMORY_CONVERSATION_TURN_BASE,
    all_memory_stream_patterns,
    conversation_turn_stream_pattern,
    conversation_turn_subject,
    memory_command_stream_pattern,
    memory_command_subject,
)

__all__ = [
    "KG_PREDICATE_VALUES",
    "MEMORY_COMMAND_BASE",
    "MEMORY_CONVERSATION_TURN_BASE",
    "SENSITIVE_PREDICATES",
    "USER_CONFIRMED_ROOM_PREFIX",
    "ConversationTurnPayload",
    "ConsolidatorIngestThemeCommand",
    "KgAddTripleCommand",
    "KgInvalidateCommand",
    "KgPredicate",
    "MemoryCommandPayload",
    "UserConfirmedFactCommand",
    "all_memory_stream_patterns",
    "conversation_turn_stream_pattern",
    "conversation_turn_subject",
    "memory_command_stream_pattern",
    "memory_command_subject",
]
