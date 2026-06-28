"""Memory JetStream payload contracts."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from ._model import EidolonWireModel
from .subjects import derive_memory_space_id, validate_memory_space_id


class MemoryActorContext(EidolonWireModel):
    """Resolved actor context carried by every memory write and recall."""

    owner_id: str
    companion_id: str
    memory_realm_id: str
    device_id: str
    session_id: str
    memory_space_id: str = ""

    @field_validator(
        "owner_id",
        "companion_id",
        "memory_realm_id",
        "device_id",
        "session_id",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("memory actor context fields cannot be blank")
        return text

    @model_validator(mode="after")
    def _fill_memory_space_id(self) -> "MemoryActorContext":
        expected = derive_memory_space_id(self.memory_realm_id)
        if self.memory_space_id:
            actual = validate_memory_space_id(self.memory_space_id)
            if self.memory_space_id != expected:
                raise ValueError(
                    "memory_space_id must equal memory_realm_id"
                )
            object.__setattr__(self, "memory_space_id", actual)
        else:
            object.__setattr__(self, "memory_space_id", expected)
        return self


class ConversationTurnPayload(EidolonWireModel):
    """One completed user/assistant turn published to memory."""

    turn_id: str
    context: MemoryActorContext
    user_text: str
    assistant_text: str
    timestamp: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_memory_actor_context(
    *,
    owner_id: str,
    companion_id: str,
    memory_realm_id: str,
    device_id: str,
    session_id: str,
) -> MemoryActorContext:
    """Build the canonical memory actor context from product identity."""

    return MemoryActorContext(
        owner_id=owner_id,
        companion_id=companion_id,
        memory_realm_id=memory_realm_id,
        device_id=device_id,
        session_id=session_id,
    )
