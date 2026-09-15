"""Device-scoped Owner policy commands; identity stays in the foundation contract."""

from pydantic import Field
from eidolon_sdk.device_foundation.v1 import DeviceRef
from . import Contract, OutputSelection


class SetDeviceOutputPolicy(Contract):
    device_ref: DeviceRef
    expected_revision: int = Field(strict=True, ge=0)
    allowed: OutputSelection
