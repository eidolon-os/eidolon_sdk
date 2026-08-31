"""The setup descriptor: what a device says about itself before it belongs to anyone.

This is the first thing a controller reads over the provisioning session, and it
was the last DTO in the commissioning act with no canonical definition. The
firmware built it with hand-written JSON and the phone app took it apart with a
hand-written field table, and the two were kept in step by a person comparing two
files. They stopped being in step the way that always happens: the device encoded
"this offer never ends" as ``expires_in_seconds: 0``, the controller required a
duration it could act on and refused, and every device out of the box was told
its own description did not match the contract. Neither end was wrong about its
own half.

So the fields live here now, and both ends are generated from this definition and
held to the same golden vector.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

from .lifecycle import DeviceInstanceId, WireEnum

SETUP_DESCRIPTOR_CONTRACT_VERSION = "1"

# How much longer a setup offer lasts, when it lasts a bounded time at all.
#
# There is no value here for an offer that does not end. That state is carried by
# the absence of the field, never by a number: a sentinel cannot be told apart
# from a field nobody filled in, and the sentinel this contract used to ship (0)
# made every uncommissioned device advertise a window its controller read as
# already closed.
SetupWindowRemainingSeconds = Annotated[int, Field(strict=True, ge=1)]


class SetupDescriptorTrust(WireEnum):
    """Whether the descriptor's identity is bound to a product credential.

    Development and production devices differ in this value only; the setup act
    that follows is the same one either way.
    """

    DEVELOPMENT_TOFU = "development-tofu"
    MANUFACTURER_BOUND = "manufacturer-bound"


class SetupDescriptor(BaseModel):
    """The device's own answer to "who are you and how long are you offering?"."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_version: Literal["1"] = SETUP_DESCRIPTOR_CONTRACT_VERSION
    device_id: DeviceInstanceId
    device_kind: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    display_name: str = Field(min_length=1, max_length=128)
    identity_fingerprint: str = Field(pattern=r"^p256:[0-9a-f]{64}$")
    session_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    # A duration, not an instant. A device being set up has not joined a network
    # and has no wall clock, so it can say how long this window lasts but not
    # when it ends; the controller turns this into the absolute expiry its own
    # contract carries, against its own clock.
    #
    # ``None`` is the offer that does not end, and it is not serialised at all.
    expires_in_seconds: SetupWindowRemainingSeconds | None = None
    # The base identity this device already holds, if any. ``None`` is a device
    # that has never been commissioned — or one whose storage was erased, which
    # is now the same statement. Forwarded to the Host and never believed on the
    # device's word: only Hub knows what it issued.
    device_base_id: str | None = Field(
        default=None,
        pattern=r"^(device-base-[0-9a-f]{64}|software-body-[0-9a-f]{40})$",
    )
    trust: SetupDescriptorTrust

    @field_validator("expires_in_seconds", mode="before")
    @classmethod
    def _absence_is_the_only_way_to_say_never(cls, value: Any) -> Any:
        """A key written with no value is the same mistake as a key written 0.

        Leaving the field out says the offer does not end. Writing the field and
        putting nothing in it says a producer reached for a stand-in, which is
        the shape of the bug that refused every device out of the box, so it is
        refused here rather than quietly read as the absence.
        """

        if value is None:
            raise ValueError("an offer with no deadline must omit expires_in_seconds")
        return value

    @model_serializer
    def _wire_form(self) -> dict[str, Any]:
        """The wire form, with the duration an endless offer does not have left out.

        Not a formatting preference: what this dumps is what a producer writes,
        and ``expires_in_seconds: null`` there is the same mistake as 0 — a key
        that exists to carry a duration, carrying a stand-in for the absence of
        one. Built from the declared fields rather than a list repeated here, so
        a field added above cannot be a field this forgets to send.
        """

        document: dict[str, Any] = {}
        for name in type(self).model_fields:
            value = getattr(self, name)
            if value is None:
                continue
            document[name] = str(value) if isinstance(value, Enum) else value
        return document


def setup_descriptor_from_json(value: Any) -> SetupDescriptor:
    """Read a descriptor exactly as strictly as the schema does."""

    return SetupDescriptor.model_validate(value)


def setup_descriptor_to_json(descriptor: SetupDescriptor) -> dict[str, Any]:
    """Render the wire form of a descriptor."""

    return descriptor.model_dump(mode="json")
