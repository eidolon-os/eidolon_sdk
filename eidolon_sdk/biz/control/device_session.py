"""One device starts and ends its own Companion conversation."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field
from eidolon_sdk.device_foundation.v1 import DeviceRef
from .device_conversation import DeviceConversationStatus

DeviceSessionStatus = DeviceConversationStatus

class DeviceSessionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: Annotated[str, Field(strict=True, min_length=1, max_length=64,
                                    pattern=r"^[A-Za-z0-9_.:-]+$")]
    device: DeviceRef
    target_companion_id: Annotated[str, Field(strict=True, min_length=1, max_length=128,
                                             pattern=r"^[A-Za-z0-9_.:-]+$")]

    @property
    def devices(self) -> tuple[DeviceRef, ...]:
        return (self.device,)
