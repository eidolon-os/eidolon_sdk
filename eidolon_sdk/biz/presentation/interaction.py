"""Session-scoped behavior facts; observations, never turn-control commands."""

from typing import Literal
from pydantic import Field
from . import Contract, Identifier

TOPIC = "eidolon.interaction.v1"


class InteractionFacts(Contract):
    version: Literal[1] = 1
    session_id: Identifier
    policy_revision: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=1)
    user_speaking: bool = Field(strict=True)
    agent_speaking: bool = Field(strict=True)
