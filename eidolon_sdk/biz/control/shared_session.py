"""Shared-session selection, before any room or invitation is created.

Authenticated Owner scope is supplied by the caller, never by this payload.
These snapshots are observations, not room admission or execution grants.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eidolon_sdk.device_foundation.v1.lifecycle import DeviceInstanceId, DeviceRef


class SharedSessionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    session_id: Annotated[
        str, Field(strict=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    ]
    devices: Annotated[tuple[DeviceRef, ...], Field(min_length=2, max_length=16)]
    input_device_id: DeviceInstanceId

    @model_validator(mode="before")
    @classmethod
    def integer_version(cls, value):
        if (
            isinstance(value, dict)
            and "schema_version" in value
            and type(value["schema_version"]) is not int
        ):
            raise ValueError("SCHEMA_VERSION_MUST_BE_INTEGER")
        return value

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        ids = [device.device_instance_id for device in self.devices]
        if len(set(ids)) != len(ids):
            raise ValueError("DUPLICATE_DEVICE")
        if self.input_device_id not in ids:
            raise ValueError("INPUT_DEVICE_NOT_SELECTED")
        domains = {
            (device.owner_domain_id, device.owner_domain_generation) for device in self.devices
        }
        if len(domains) != 1:
            raise ValueError("MIXED_OWNER_DOMAIN")
        return self


class SharedChannelSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    device_ref: DeviceRef
    channel_id: str
    manifest_revision: str
    expires_at_ms: int
