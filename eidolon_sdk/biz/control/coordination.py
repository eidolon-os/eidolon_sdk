"""An IP role-group scene selection, not a global conversation policy.

The management boundary resolves current DeviceRefs after authenticating the
Owner. Every lifecycle, device capability and Companion runtime scope must be
checked before preparing any endpoint. Member order is configuration order;
only a decision proposal determines response order. Solo conversations retain
their existing input modes and do not use this contract.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from eidolon_sdk.device_foundation.v1 import DeviceRef

Identifier = Annotated[
    str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
]


class SceneRole(BaseModel):
    """Temporary performance data; never a Companion binding or tool grant."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=1000)] = ""


class CoordinationMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    companion_id: Identifier
    output_device: DeviceRef
    role: SceneRole | None = None


class CoordinationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    scenario: Literal["ip_role_group"]
    session_id: Annotated[
        str, Field(strict=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    ]
    input_device: DeviceRef
    input_mode: Literal["ptt"] = "ptt"
    members: Annotated[tuple[CoordinationMember, ...], Field(min_length=1, max_length=16)]
    goal: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=2000)] = ""
    reply_budget: Annotated[int, Field(strict=True, ge=1, le=32)] = 8
    # Immutable for this scene. Changing assignments requires a new scene.
    assignment_revision: Literal[1] = 1

    @model_validator(mode="before")
    @classmethod
    def integer_version(cls, value):
        if isinstance(value, dict):
            for key in ("schema_version", "assignment_revision"):
                if key in value and type(value[key]) is not int:
                    raise ValueError("VERSION_MUST_BE_INTEGER")
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


class RoleGroupStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: Identifier
    state: Literal["preparing", "ready", "closing", "closed", "failed"]
    error: str = ""
    scenario: Literal["ip_role_group"]
    completion_basis: Literal["native_playout"]


# Physical execution and receipt delivery have separate bounded budgets.
STOP_EXECUTION_TIMEOUT = 2.0
STOP_RECEIPT_TIMEOUT = STOP_EXECUTION_TIMEOUT + 1.0
