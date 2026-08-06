"""Cross-authority audit envelope and publishing port.

This module deliberately contains no database, NATS, or process lifecycle
code. Each authority owns its local transaction/outbox implementation; global
audit infrastructure only consumes this stable wire contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class AuditEnvelope(BaseModel):
    """One immutable governance fact or terminal cross-authority receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["eidolon.audit.v1"] = "eidolon.audit.v1"
    event_id: str = Field(min_length=1, max_length=64)
    producer: str = Field(min_length=1, max_length=64)
    producer_seq: int = Field(ge=1)
    category: Literal["governance", "receipt"]
    owner_id: str | None = Field(default=None, max_length=64)
    subject_type: str = Field(min_length=1, max_length=64)
    subject_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=128)
    outcome: Literal["success", "failure", "denied", "deferred"] = "success"
    severity: Literal["info", "warn", "error", "critical"] = "info"
    reason: str | None = Field(default=None, max_length=256)
    trace_id: str | None = Field(default=None, max_length=64)
    data_classification: Literal["safe", "sensitive", "restricted"] = "safe"
    schema_version: int = Field(default=1, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class AuditPublisher(Protocol):
    """Transport port implemented at the composition/infrastructure edge."""

    async def publish_many(self, events: list[AuditEnvelope]) -> set[str]:
        """Return event IDs durably acknowledged by the transport."""
