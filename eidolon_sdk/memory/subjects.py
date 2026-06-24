"""Memory-related NATS subject contracts."""

from __future__ import annotations

import re

MEMORY_CONVERSATION_TURN_BASE = "eidolon.memory.turn"
MEMORY_COMMAND_BASE = "eidolon.memory.cmd"
MEMORY_SYNC_BASE = "eidolon.memory.sync"

_MEMORY_SPACE_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
    r"\.[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
    r"\.[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
)


def validate_memory_space_id(memory_space_id: str) -> str:
    """Validate ``<tenant_id>.<owner_user_id>.<persona_id>`` subject suffixes."""

    value = (memory_space_id or "").strip()
    if not _MEMORY_SPACE_ID_RE.fullmatch(value):
        raise ValueError(
            "memory_space_id must match "
            "<tenant_id>.<owner_user_id>.<persona_id> with safe ASCII ids; "
            f"got {memory_space_id!r}"
        )
    return value


def derive_memory_space_id(tenant_id: str, owner_user_id: str, persona_id: str) -> str:
    """Build and validate the canonical memory-space id."""

    return validate_memory_space_id(f"{tenant_id}.{owner_user_id}.{persona_id}")


def conversation_turn_subject(memory_space_id: str) -> str:
    """Return the JetStream subject for a completed turn."""

    return f"{MEMORY_CONVERSATION_TURN_BASE}.{validate_memory_space_id(memory_space_id)}"


def conversation_turn_stream_pattern() -> str:
    """Wildcard subject pattern for conversation turn consumers."""

    return f"{MEMORY_CONVERSATION_TURN_BASE}.>"


def memory_command_subject(memory_space_id: str) -> str:
    """Return the JetStream subject for memory command writes."""

    return f"{MEMORY_COMMAND_BASE}.{validate_memory_space_id(memory_space_id)}"


def memory_command_stream_pattern() -> str:
    """Wildcard subject pattern for memory command consumers."""

    return f"{MEMORY_COMMAND_BASE}.>"


def memory_sync_subject(memory_space_id: str) -> str:
    """Return the JetStream subject for offline-device sync batches."""

    return f"{MEMORY_SYNC_BASE}.{validate_memory_space_id(memory_space_id)}"


def memory_sync_stream_pattern() -> str:
    """Wildcard subject pattern for offline-device sync batches."""

    return f"{MEMORY_SYNC_BASE}.>"


def all_memory_stream_patterns() -> list[str]:
    """Subjects the memory JetStream stream should bind."""

    return [
        conversation_turn_stream_pattern(),
        memory_command_stream_pattern(),
        memory_sync_stream_pattern(),
    ]
