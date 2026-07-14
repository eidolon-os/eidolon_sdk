"""Strict contracts for Admin-authoritative Owner Face Profile delivery.
The profile plane is deliberately separate from Guard facts, policy config,
and runtime config. Control commands carry only desired revision metadata.
Reference media is fetched from authenticated device endpoints by opaque id.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OWNER_FACE_PROFILE_SCHEMA_VERSION = 1
OWNER_FACE_PROFILE_MIN_REFERENCES = 3
OWNER_FACE_PROFILE_MAX_REFERENCES = 5
OWNER_FACE_PROFILE_REQUIRED_POSES = frozenset({"front", "left", "right"})

OwnerFacePose = Literal["front", "left", "right", "down", "up"]
OwnerFaceDesiredState = Literal["active", "cleared"]


class GuardOwnerFaceReferenceManifest(BaseModel):
    """One normalized reference object exposed to an authenticated Guard."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    reference_id: str = Field(min_length=1, max_length=96)
    pose: OwnerFacePose
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=4 * 1024 * 1024)
    content_type: Literal["image/jpeg"] = "image/jpeg"


class GuardOwnerFaceProfileManifest(BaseModel):
    """Desired profile returned only from the signed Guard pull endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_v: Literal[OWNER_FACE_PROFILE_SCHEMA_VERSION] = OWNER_FACE_PROFILE_SCHEMA_VERSION
    binding_id: str = Field(min_length=1, max_length=64)
    profile_id: str = Field(min_length=1, max_length=64)
    profile_revision: int = Field(ge=1)
    desired_state: OwnerFaceDesiredState
    model_id: str | None = Field(default=None, min_length=1, max_length=96)
    preprocessing_version: str | None = Field(default=None, min_length=1, max_length=96)
    references: tuple[GuardOwnerFaceReferenceManifest, ...] = Field(
        default=(),
        max_length=OWNER_FACE_PROFILE_MAX_REFERENCES,
    )

    @field_validator("references", mode="before")
    @classmethod
    def _references_accept_json_arrays(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def _validate_state(self) -> "GuardOwnerFaceProfileManifest":
        if self.desired_state == "cleared":
            if self.references or self.model_id is not None or self.preprocessing_version is not None:
                raise ValueError("cleared owner face profile must not contain model or references")
            return self

        if self.model_id is None or self.preprocessing_version is None:
            raise ValueError("active owner face profile requires model compatibility metadata")
        if len(self.references) < OWNER_FACE_PROFILE_MIN_REFERENCES:
            raise ValueError("active owner face profile requires at least three references")
        reference_ids = [reference.reference_id for reference in self.references]
        poses = [reference.pose for reference in self.references]
        if len(set(reference_ids)) != len(reference_ids):
            raise ValueError("owner face reference ids must be unique")
        if len(set(poses)) != len(poses):
            raise ValueError("owner face reference poses must be unique")
        if not OWNER_FACE_PROFILE_REQUIRED_POSES.issubset(poses):
            raise ValueError("owner face profile requires front, left, and right references")
        return self


class GuardOwnerFaceProfileSync(BaseModel):
    """Media-free payload carried by the generic command envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    binding_id: str = Field(min_length=1, max_length=64)
    profile_id: str = Field(min_length=1, max_length=64)
    profile_revision: int = Field(ge=1)
    desired_state: OwnerFaceDesiredState


class GuardOwnerFaceProfileApplyResult(BaseModel):
    """Non-sensitive successful apply/clear fact returned by a Guard device."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    binding_id: str = Field(min_length=1, max_length=64)
    profile_id: str = Field(min_length=1, max_length=64)
    profile_revision: int = Field(ge=1)
    applied_state: OwnerFaceDesiredState
    model_id: str | None = Field(default=None, min_length=1, max_length=96)
    preprocessing_version: str | None = Field(default=None, min_length=1, max_length=96)
    template_count: int = Field(ge=0, le=OWNER_FACE_PROFILE_MAX_REFERENCES)

    @model_validator(mode="after")
    def _validate_state(self) -> "GuardOwnerFaceProfileApplyResult":
        if self.applied_state == "cleared":
            if self.template_count != 0 or self.model_id is not None or self.preprocessing_version is not None:
                raise ValueError("cleared owner face result must not retain model or templates")
            return self
        if self.model_id is None or self.preprocessing_version is None:
            raise ValueError("active owner face result requires model compatibility metadata")
        if self.template_count < OWNER_FACE_PROFILE_MIN_REFERENCES:
            raise ValueError("active owner face result requires at least three templates")
        return self


def parse_guard_owner_face_profile_manifest(payload: object) -> GuardOwnerFaceProfileManifest:
    return GuardOwnerFaceProfileManifest.model_validate(payload)


def parse_guard_owner_face_profile_sync(payload: object) -> GuardOwnerFaceProfileSync:
    return GuardOwnerFaceProfileSync.model_validate(payload)


def parse_guard_owner_face_profile_apply_result(
    payload: object,
) -> GuardOwnerFaceProfileApplyResult:
    return GuardOwnerFaceProfileApplyResult.model_validate(payload)
