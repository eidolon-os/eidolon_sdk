"""A fixed machine power operation; no caller-supplied command or arguments."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HostPowerStatusWire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    can_power_off: bool
    unavailable_reason: str | None = None


class HostPowerOffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")


class HostPowerOffAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation: Literal["system.poweroff"] = "system.poweroff"
    request_id: str
    status: Literal["accepted"] = "accepted"
