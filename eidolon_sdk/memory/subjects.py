"""Memory-related NATS subject contracts.

These subjects are the public bus contract between agent, admin, and memory.
Keep business handling in the owning projects; this module only constructs
stable wire names.
"""

from __future__ import annotations

import re

MEMORY_CONVERSATION_TURN_BASE = "agent.memory.conversation.turn"
MEMORY_COMMAND_BASE = "agent.memory.cmd"

_MEMORY_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_memory_subject_user_id(user_id: str) -> str:
    """Validate user ids embedded in NATS subjects.

    Memory historically allows dots in user ids, so this is intentionally a
    little wider than the registry id charset. It still rejects empty values,
    separators, and control characters that would break the subject hierarchy.
    """

    uid = (user_id or "").strip()
    if not _MEMORY_USER_ID_RE.fullmatch(uid):
        raise ValueError(
            f"user_id must match {_MEMORY_USER_ID_RE.pattern}; got {user_id!r}"
        )
    return uid


def conversation_turn_subject(user_id: str) -> str:
    """Return the per-user JetStream subject for a completed turn."""

    return f"{MEMORY_CONVERSATION_TURN_BASE}.{validate_memory_subject_user_id(user_id)}"


def conversation_turn_stream_pattern() -> str:
    """Wildcard subject pattern for conversation turn consumers."""

    return f"{MEMORY_CONVERSATION_TURN_BASE}.>"


def memory_command_subject(user_id: str) -> str:
    """Return the per-user JetStream subject for memory command writes."""

    return f"{MEMORY_COMMAND_BASE}.{validate_memory_subject_user_id(user_id)}"


def memory_command_stream_pattern() -> str:
    """Wildcard subject pattern for memory command consumers."""

    return f"{MEMORY_COMMAND_BASE}.>"


def all_memory_stream_patterns() -> list[str]:
    """Subjects the memory JetStream stream should bind."""

    return [
        conversation_turn_stream_pattern(),
        memory_command_stream_pattern(),
    ]
