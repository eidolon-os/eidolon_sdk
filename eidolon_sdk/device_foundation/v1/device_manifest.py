"""Device-asserted capability Manifest: what a device can do, as of now.

A Manifest used to be captured once, inside the enrollment that became a Claim,
and was immutable for the life of that Claim. Two different things had been
given one lifetime: *who this device is*, which the Owner approves and which
must not drift, and *what this device can do*, which changes every time its
firmware does.

The consequence was not theoretical. A device that enrolled while declaring an
incomplete Manifest could never correct it, because the only way to replace a
frozen Manifest was to remove the Claim and enrol again — and removal requires a
person physically present at the hardware. A capability record that can only be
repaired by hand is not a record of a capability.

So the Manifest is asserted here, on the device-authenticated Device Control
surface, by the only party that knows the answer, as often as the answer
changes. The Owner's approval still governs identity; it never governed this.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .lifecycle import (
    DeviceRef,
    ManifestDocument,
    ManifestRef,
    _aware_datetime,
)

MANIFEST_ASSERTION_OPERATION = "device-control.manifest-assert"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AssertDeviceManifest(_Model):
    contract: Literal["eidolon.device-foundation.manifest-assertion"] = (
        "eidolon.device-foundation.manifest-assertion"
    )
    contract_version: Literal["1.0"] = "1.0"
    device_ref: DeviceRef
    manifest: ManifestDocument
    nonce: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    public_key_spki: str = Field(min_length=120, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    device_signature: str = Field(min_length=86, max_length=86, pattern=r"^[A-Za-z0-9_-]+$")

    def signing_document(self) -> dict[str, object]:
        """Signs the content by its digest, which the Authority recomputes.

        Carrying the digest rather than the document keeps the document a device
        has to canonicalize down to what it already computed, while still making
        the signature refuse to carry from one set of capabilities to another.
        """

        return {
            "device_ref": self.device_ref.model_dump(mode="json"),
            "manifest_digest": self.manifest.digest,
            "nonce": self.nonce,
            "operation_type": MANIFEST_ASSERTION_OPERATION,
        }


class DeviceManifestAcceptance(_Model):
    contract: Literal["eidolon.device-foundation.manifest-acceptance"] = (
        "eidolon.device-foundation.manifest-acceptance"
    )
    contract_version: Literal["1.0"] = "1.0"
    device_ref: DeviceRef
    nonce: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    accepted: ManifestRef
    # A device asserts on every boot, so "I already knew that" is the common
    # answer and is not an error. It is distinguished from a change because only
    # a change is worth an event, and only a change invalidates a binding.
    outcome: Literal["accepted", "unchanged"]
    accepted_at: datetime

    @field_validator("accepted_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)
