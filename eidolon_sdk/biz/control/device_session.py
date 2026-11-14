"""One device's own Companion conversation, as its Owner sees and asks for it.

The conversation belongs to the device: the device starts it (a gesture, a wake
word, or because its Owner asked it to) and names it. An Owner therefore
addresses the device, never a conversation object of their own.
"""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
from eidolon_sdk.biz.contracts import SESSION_CONVERSATION_ID_MAX_LENGTH
from eidolon_sdk.device_foundation.v1 import DeviceInstanceId, DeviceRef

ConversationId = Annotated[str, Field(strict=True, min_length=1,
    max_length=SESSION_CONVERSATION_ID_MAX_LENGTH, pattern=r"^[A-Za-z0-9_.:-]+$")]


class DeviceSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    device: DeviceRef
    # Close only: end this conversation, not one the device started since.
    conversation_id: ConversationId | None = None

    @property
    def devices(self) -> tuple[DeviceRef, ...]:
        return (self.device,)


class DeviceSessionStatus(BaseModel):
    """`starting` is only ever the answer to an open: the device accepted the
    request and has not asked for its conversation yet. `occupied` is a
    cross-device or team conversation holding the device; it ends there."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    device_id: DeviceInstanceId
    state: Literal["standby", "starting", "in_conversation", "closing", "occupied"]
    conversation_id: ConversationId | None = None
    error: str = ""
