"""Strict Python binding for the shared Host Vitals V1 contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HOST_VITALS_CONTRACT = "https://contracts.eidolon.live/system/v1/host-vitals.schema.json"
HOST_VITALS_OPERATION = "system.host-vitals"


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MeasurementWire(_ContractModel):
    """One raw reading, or the explicit reason it could not be taken."""

    name: str = Field(min_length=1, max_length=64)
    value: float | None
    unit: str
    capacity: float | None
    unavailable_reason: str | None = Field(max_length=256)


class HostVitalsWire(_ContractModel):
    """Machine-scoped observations; deliberately not a health verdict."""

    operation: Literal["system.host-vitals"]
    observed_at: datetime
    measurements: tuple[MeasurementWire, ...]

    @field_validator("measurements", mode="before")
    @classmethod
    def _arrays(cls, value):
        return tuple(value) if isinstance(value, list) else value
