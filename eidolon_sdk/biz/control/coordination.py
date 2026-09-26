"""A coordinated scene selection, not an authorization or a playback grant.

The management boundary resolves current DeviceRefs after authenticating the
Owner. Every lifecycle, device capability and Companion runtime scope must be
checked before preparing any endpoint. Member order is configuration order;
only a decision proposal determines response order.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eidolon_sdk.device_foundation.v1 import DeviceRef

Identifier = Annotated[
    str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
]


class CoordinationMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    companion_id: Identifier
    output_device: DeviceRef


class CoordinationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    session_id: Annotated[
        str, Field(strict=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    ]
    input_device: DeviceRef
    input_mode: Literal["ptt"] = "ptt"
    members: Annotated[tuple[CoordinationMember, ...], Field(min_length=1, max_length=16)]
    discussion: Annotated[bool, Field(strict=True)] = False
    reply_budget: Annotated[int, Field(strict=True, ge=1, le=32)] = 8

    @model_validator(mode="before")
    @classmethod
    def integer_version(cls, value):
        if isinstance(value, dict) and "schema_version" in value:
            if type(value["schema_version"]) is not int:
                raise ValueError("SCHEMA_VERSION_MUST_BE_INTEGER")
        return value

    @property
    def devices(self) -> tuple[DeviceRef, ...]:
        return (self.input_device, *(member.output_device for member in self.members))

    @model_validator(mode="after")
    def validate_membership(self) -> Self:
        ids = [device.device_instance_id for device in self.devices]
        if len(set(ids)) != len(ids):
            raise ValueError("INPUT_AND_OUTPUT_DEVICES_MUST_BE_DISTINCT")
        companions = [member.companion_id for member in self.members]
        if len(set(companions)) != len(companions):
            raise ValueError("DUPLICATE_COMPANION")
        domains = {(ref.owner_domain_id, ref.owner_domain_generation) for ref in self.devices}
        if len(domains) != 1:
            raise ValueError("MIXED_OWNER_DOMAIN")
        return self
