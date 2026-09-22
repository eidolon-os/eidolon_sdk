"""Device-scoped Owner policy commands; identity stays in the foundation contract."""

from pydantic import Field
from eidolon_sdk.device_foundation.v1 import DeviceRef
from . import Contract, DeviceOutputPolicy, OutputSelection, InputSelection


class SetDeviceOutputPolicy(Contract):
    device_ref: DeviceRef
    expected_revision: int = Field(strict=True, ge=0)
    allowed: OutputSelection
    inputs: InputSelection | None = None


class ReadDeviceOutputPolicy(Contract):
    device_ref: DeviceRef


class DeviceOutputConfiguration(Contract):
    """What one device can present, and what its Owner has allowed it to.

    Two different facts, answered together because a management surface needs
    both to say anything true: what the device declared it can do never changes
    with authorization, and what it may do is nobody's decision but the Owner's.

    ``capabilities`` is derived from the accepted Manifest, not stored beside
    it. ``policy`` is ``None`` when the Owner has not decided yet, which is not
    the same answer as a policy that allows nothing — one is a question still
    open, the other is an answer.
    """

    device_ref: DeviceRef
    capabilities: OutputSelection
    input_capabilities: InputSelection | None = None
    policy: DeviceOutputPolicy | None = None
    # None is a response from a pre-contract Hub, not an explicit opt-out.
    policy_required: bool | None = Field(default=None, strict=True)
