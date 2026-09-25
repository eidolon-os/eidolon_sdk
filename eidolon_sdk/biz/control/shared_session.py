"""Shared-session selection, before any room or invitation is created.

Authenticated Owner scope is supplied by the caller, never by this payload.
These snapshots are observations, not room admission or execution grants.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .channel_binding import ChannelBinding
from .protocol import build_command_envelope

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
    # Original-channel presence is not shared-room readiness or admission.
    on_channel: bool | None = None
    observed_at_ms: int | None = None


class SharedSessionInvitation(BaseModel):
    """Payload of shared-session.invite in the existing command envelope.

    Envelope ID is the invitation/retry key. Its authenticated transport binds
    the issuer; DeviceRef fences the receiver's current lifecycle. Accepting
    this payload is not permission to start an Agent. The temporary binding
    must never overwrite the device's durable configuration. On exit the
    device refreshes its original configuration through normal Device Control.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    session_id: Annotated[
        str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    ]
    device_ref: DeviceRef
    deadline_ms: Annotated[int, Field(gt=0)]
    channel: ChannelBinding = Field(repr=False)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("SCHEMA_VERSION_MUST_BE_INTEGER")
        return value

    @model_validator(mode="after")
    def validate_invitation(self) -> Self:
        if self.channel.purpose != "shared-session":
            raise ValueError("TEMPORARY_SHARED_CHANNEL_REQUIRED")
        if not self.channel.issued_at_ms < self.deadline_ms <= self.channel.expires_at_ms:
            raise ValueError("INVITATION_DEADLINE_OUTSIDE_GRANT")
        return self


    def command(self, *, command_id: str) -> dict:
        """Build wire bytes' envelope; src is a label, not authentication.

        The sender must use its authenticated control transport, and receivers
        must verify both transport identity and their full current DeviceRef.
        A retry keeps this ID and the original issue/deadline times unchanged.
        """
        if not isinstance(command_id, str) or not command_id.strip() or len(command_id) > 128:
            raise ValueError("INVITATION_COMMAND_ID_REQUIRED")
        return build_command_envelope(
            command_id=command_id,
            device_id=self.device_ref.device_instance_id,
            payload=self.model_dump(mode="json"),
            op="shared-session.invite",
            ttl_ms=self.deadline_ms - self.channel.issued_at_ms,
            src_type="channel", src_id="channel-provider",
            created_at=datetime.fromtimestamp(self.channel.issued_at_ms / 1000, UTC),
        )
