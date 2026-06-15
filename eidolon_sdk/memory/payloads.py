"""Memory JetStream payload contracts."""

from __future__ import annotations

from typing import Any

from ._model import EidolonWireModel


class ConversationTurnPayload(EidolonWireModel):
    """One completed user/assistant turn published to memory."""

    turn_id: str
    user_text: str
    assistant_text: str
    timestamp: str
    session_id: str = ""
    user_id: str = ""
    metadata: dict[str, Any] | None = None
