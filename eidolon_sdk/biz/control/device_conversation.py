"""Explicit single-Companion input/presentation selection for existing devices.

Owner identity is supplied by authentication. DeviceRef fences each current
lifecycle; this selection never changes a permanent Companion attachment.
"""
from typing import Annotated, Literal, Self
from pydantic import BaseModel, ConfigDict, Field, model_validator
from eidolon_sdk.device_foundation.v1 import DeviceRef


class DeviceConversationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: Annotated[str, Field(strict=True, min_length=1, max_length=64,
                                    pattern=r"^[A-Za-z0-9_.:-]+$")]
    input_device: DeviceRef
    output_device: DeviceRef
    target_companion_id: Annotated[str, Field(strict=True, min_length=1, max_length=128,
                                             pattern=r"^[A-Za-z0-9_.:-]+$")]

    @model_validator(mode="after")
    def endpoints(self) -> Self:
        source, target = self.input_device, self.output_device
        if source.device_instance_id == target.device_instance_id:
            raise ValueError("DISTINCT_ENDPOINTS_REQUIRED")
        if (source.owner_domain_id, source.owner_domain_generation) != (
            target.owner_domain_id, target.owner_domain_generation
        ):
            raise ValueError("MIXED_OWNER_DOMAIN")
        return self

    @property
    def devices(self) -> tuple[DeviceRef, DeviceRef]:
        return self.input_device, self.output_device


class DeviceConversationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: Annotated[str, Field(strict=True, min_length=1, max_length=64,
                                    pattern=r"^[A-Za-z0-9_.:-]+$")]
    state: Literal["preparing", "ready", "closing", "closed", "failed"]
    error: str = ""
