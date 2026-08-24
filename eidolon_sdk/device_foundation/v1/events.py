"""Strict canonical Claim lifecycle CloudEvent and recovery-stream bindings."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .lifecycle import (
    WireEnum,
    BusinessOwnerId,
    DeviceRef,
    ManifestRef,
    OwnerDomainId,
    _aware_datetime,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AdmissionEventSource(WireEnum):
    ADMISSION = "urn:eidolon:authority:admission"


class AdmissionEventType(WireEnum):
    PROPOSAL_CREATED = "live.eidolon.device.enrollment-proposal-created.v1"
    APPROVED = "live.eidolon.device.enrollment-approved.v1"
    REJECTED = "live.eidolon.device.enrollment-rejected.v1"
    EXPIRED = "live.eidolon.device.enrollment-expired.v1"
    CANCELED = "live.eidolon.device.enrollment-canceled.v1"
    GRANT_DELIVERED = "live.eidolon.device.claim-grant-delivered.v1"
    GRANT_ACKNOWLEDGED = "live.eidolon.device.claim-grant-acknowledged.v1"
    CLAIM_ACTIVATED = "live.eidolon.device.claim-activated.v1"
    CLAIM_SUSPENDED = "live.eidolon.device.claim-suspended.v1"
    CLAIM_RESUMED = "live.eidolon.device.claim-resumed.v1"
    CLAIM_REVOKED = "live.eidolon.device.claim-revoked.v1"
    TRUST_EPOCH_CHANGED = "live.eidolon.device.claim-trust-epoch-changed.v1"
    MANIFEST_ACCEPTED = "live.eidolon.device.manifest-accepted.v1"


class ClaimActivatedData(_Model):
    device_ref: DeviceRef
    business_owner_id: BusinessOwnerId
    manifest_ref: ManifestRef
    approval_decision_id: str = Field(min_length=3, max_length=128)
    activated_at: datetime

    @field_validator("activated_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class ClaimRevokedData(_Model):
    device_ref: DeviceRef
    reason: str = Field(min_length=1, max_length=256)
    revoked_at: datetime

    @field_validator("revoked_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class _ClaimEvent(_Model):
    specversion: Literal["1.0"] = "1.0"
    id: str = Field(min_length=3, max_length=128)
    source: Literal["urn:eidolon:authority:admission"] = "urn:eidolon:authority:admission"
    subject: str = Field(pattern=r"^device-instances/[A-Za-z0-9][A-Za-z0-9._:-]*$")
    time: datetime
    datacontenttype: Literal["application/json"] = "application/json"
    audience: Literal["eidolon-claim-consumers"] = "eidolon-claim-consumers"
    ownerdomainid: OwnerDomainId
    aggregaterev: int = Field(ge=1)
    correlationid: str = Field(min_length=3, max_length=128)
    causationid: str = Field(min_length=3, max_length=128)

    @field_validator("time", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class ClaimActivatedEvent(_ClaimEvent):
    type: Literal["live.eidolon.device.claim-activated.v1"] = (
        "live.eidolon.device.claim-activated.v1"
    )
    dataschema: Literal[
        "https://contracts.eidolon.live/device-foundation/v1/events/claim-activated-data.schema.json"
    ] = "https://contracts.eidolon.live/device-foundation/v1/events/claim-activated-data.schema.json"
    data: ClaimActivatedData

    @model_validator(mode="after")
    def _scope(self) -> ClaimActivatedEvent:
        if self.ownerdomainid != self.data.device_ref.owner_domain_id:
            raise ValueError("ClaimActivated Owner Domain does not match DeviceRef")
        if self.subject != f"device-instances/{self.data.device_ref.device_instance_id}":
            raise ValueError("ClaimActivated subject does not match DeviceRef")
        if self.time != self.data.activated_at:
            raise ValueError("ClaimActivated event time does not match data")
        return self


class ClaimRevokedEvent(_ClaimEvent):
    type: Literal["live.eidolon.device.claim-revoked.v1"] = (
        "live.eidolon.device.claim-revoked.v1"
    )
    dataschema: Literal[
        "https://contracts.eidolon.live/device-foundation/v1/events/claim-revoked-data.schema.json"
    ] = "https://contracts.eidolon.live/device-foundation/v1/events/claim-revoked-data.schema.json"
    data: ClaimRevokedData

    @model_validator(mode="after")
    def _scope(self) -> ClaimRevokedEvent:
        if self.ownerdomainid != self.data.device_ref.owner_domain_id:
            raise ValueError("ClaimRevoked Owner Domain does not match DeviceRef")
        if self.subject != f"device-instances/{self.data.device_ref.device_instance_id}":
            raise ValueError("ClaimRevoked subject does not match DeviceRef")
        if self.time != self.data.revoked_at:
            raise ValueError("ClaimRevoked event time does not match data")
        return self


ClaimLifecycleEvent = Annotated[
    ClaimActivatedEvent | ClaimRevokedEvent,
    Field(discriminator="type"),
]


class ClaimEventCursor(_Model):
    stream_id: Literal["admission-claims-v1"] = "admission-claims-v1"
    stream_position: int = Field(ge=0)


class ClaimEventStreamItem(_Model):
    stream_position: int = Field(ge=1)
    event: ClaimLifecycleEvent


class ClaimEventPage(_Model):
    stream_id: Literal["admission-claims-v1"] = "admission-claims-v1"
    requested_after: ClaimEventCursor
    events: tuple[ClaimEventStreamItem, ...] = Field(default=(), max_length=500)
    next_cursor: ClaimEventCursor
    high_watermark: int = Field(ge=0)
    observed_at: datetime

    @field_validator("events", mode="before")
    @classmethod
    def _events(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("observed_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _contiguous(self) -> ClaimEventPage:
        if self.requested_after.stream_id != self.stream_id or self.next_cursor.stream_id != self.stream_id:
            raise ValueError("claim event cursor stream mismatch")
        positions = [item.stream_position for item in self.events]
        expected = list(
            range(self.requested_after.stream_position + 1, self.requested_after.stream_position + 1 + len(positions))
        )
        if positions != expected:
            raise ValueError("claim event page contains a stream gap or duplicate")
        expected_next = positions[-1] if positions else self.requested_after.stream_position
        if self.next_cursor.stream_position != expected_next:
            raise ValueError("claim event next cursor does not checkpoint the last item")
        if self.high_watermark < expected_next:
            raise ValueError("claim event high watermark precedes the page cursor")
        return self
