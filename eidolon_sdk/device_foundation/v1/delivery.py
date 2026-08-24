"""Canonical transport-neutral Device Delivery Port envelopes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .lifecycle import DeviceRef


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _aware(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return value.astimezone(UTC)


def _uri(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme:
        raise ValueError("payload_schema must be an absolute URI")
    return value


class DeliverEnvelope(_Model):
    delivery_attempt_id: str = Field(min_length=3, max_length=128)
    message_id: str = Field(min_length=3, max_length=128)
    kind: Literal["twin_delta", "operation", "stop_generation"]
    device_ref: DeviceRef
    deadline: datetime
    payload_schema: str = Field(min_length=1, max_length=2048)
    payload: dict[str, Any]

    @field_validator("deadline", mode="before")
    @classmethod
    def _deadline(cls, value: object) -> datetime:
        return _aware(value)

    @field_validator("payload_schema")
    @classmethod
    def _payload_schema(cls, value: str) -> str:
        return _uri(value)


class DeliveryAcceptance(_Model):
    delivery_attempt_id: str = Field(min_length=3, max_length=128)
    state: Literal["accepted", "rejected"]
    adapter_code: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _coherent(self) -> DeliveryAcceptance:
        if (self.state == "accepted") != (self.adapter_code is None):
            raise ValueError("adapter_code must be null only for accepted delivery")
        return self


class DeviceEvidenceEnvelope(_Model):
    """Transport wrapper; the nested evidence retains its device signature."""

    delivery_attempt_id: str = Field(min_length=3, max_length=128)
    message_id: str = Field(min_length=3, max_length=128)
    kind: Literal["operation_ack"] = "operation_ack"
    device_ref: DeviceRef
    payload_schema: str = Field(min_length=1, max_length=2048)
    payload: dict[str, Any]

    @field_validator("payload_schema")
    @classmethod
    def _payload_schema(cls, value: str) -> str:
        return _uri(value)
