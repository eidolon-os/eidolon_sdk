"""Saved team assets; runtime uses the existing authorized scene contract."""

from collections.abc import Mapping
from typing import Annotated, Self
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from eidolon_sdk.device_foundation.v1 import DeviceInstanceId, DeviceRef
from .coordination import CoordinationMember, CoordinationSelection, Identifier, RoleGroupStatus


class TeamMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    companion_id: Identifier
    output_device_id: DeviceInstanceId


class TeamConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=80)
    ]
    input_device_id: DeviceInstanceId
    members: Annotated[tuple[TeamMember, ...], Field(min_length=1, max_length=16)]
    goal: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=2000)] = (
        ""
    )

    @model_validator(mode="after")
    def distinct_resources(self) -> Self:
        devices = [self.input_device_id, *(m.output_device_id for m in self.members)]
        if len(set(devices)) != len(devices):
            raise ValueError("INPUT_AND_OUTPUT_DEVICES_MUST_BE_DISTINCT")
        companions = [m.companion_id for m in self.members]
        if len(set(companions)) != len(companions):
            raise ValueError("DUPLICATE_COMPANION")
        return self

    def resolve(
        self,
        *,
        session_id: str,
        devices: Mapping[str, DeviceRef],
        attachments: Mapping[str, str | None],
    ) -> CoordinationSelection:
        """Caller authorizes fresh refs; Provider still checks availability/locks.

        Never substitute members after rebinding or omit unavailable devices.
        """
        for device_id in (self.input_device_id, *(m.output_device_id for m in self.members)):
            if device_id not in devices:
                raise ValueError("TEAM_DEVICE_UNAVAILABLE")
            if devices[device_id].device_instance_id != device_id:
                raise ValueError("TEAM_DEVICE_IDENTITY_MISMATCH")
        for member in self.members:
            if attachments.get(member.output_device_id) != member.companion_id:
                raise ValueError("TEAM_BINDING_CHANGED")
        return CoordinationSelection(
            scenario="ip_role_group",
            session_id=session_id,
            input_device=devices[self.input_device_id],
            members=tuple(
                CoordinationMember(
                    companion_id=m.companion_id,
                    output_device=devices[m.output_device_id],
                )
                for m in self.members
            ),
            goal=self.goal,
        )


class TeamRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    team_id: Identifier
    revision: Annotated[int, Field(strict=True, ge=1)]
    configuration: TeamConfiguration


class TeamWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    configuration: TeamConfiguration


class TeamPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    teams: tuple[TeamRevision, ...]
    next_cursor: str | None = None


class TeamStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    session_id: Annotated[str, Field(strict=True, min_length=1, max_length=64,
                                     pattern=r"^[A-Za-z0-9_.:-]+$")]


class TeamDeleted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    team_id: Identifier


class TeamStartRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    team_id: Identifier
    session_id: Identifier
    revision: Annotated[int, Field(strict=True, ge=1)]
    closed: bool


class TeamStarts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    starts: tuple[TeamStartRecord, ...]
    next_cursor: str | None = None


class TeamStartSnapshot(TeamStartRecord):
    """Internal accepted execution snapshot; not a second runtime state machine."""
    selection: CoordinationSelection | None = None
    terminal_status: RoleGroupStatus | None = None


class TeamConflict(BaseModel):
    """Owner-scoped locator derived from a still-active immutable run snapshot."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    team_id: Identifier
    name: str
    session_id: Identifier
    revision: int
    companion_ids: tuple[Identifier, ...] = ()
    device_ids: tuple[DeviceInstanceId, ...] = ()


class TeamConflicts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    conflicts: tuple[TeamConflict, ...] = ()
    unresolved_runs: int = 0
