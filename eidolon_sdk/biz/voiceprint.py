"""Voiceprint management and admission wire contracts, independent of inference."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedSample(Contract):
    model_id: str = Field(min_length=1, max_length=128)
    weights_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str = Field(min_length=1, max_length=128)
    vector: list[float] = Field(min_length=2, max_length=2048)
    speech_ms: int = Field(ge=1500, le=30000)
    quality: dict[str, float] = Field(default_factory=dict)

    @field_validator("vector")
    @classmethod
    def valid_vector(cls, value):
        if not all(math.isfinite(x) for x in value):
            raise ValueError("non-finite embedding")
        norm = math.hypot(*value)
        if not math.isfinite(norm) or norm < 1e-8:
            raise ValueError("empty embedding")
        return [x / norm for x in value]

    @field_validator("quality")
    @classmethod
    def valid_quality(cls, value):
        if len(value) > 16 or any(len(k) > 64 or not math.isfinite(v) for k, v in value.items()):
            raise ValueError("invalid quality measurements")
        return value


class EnrollmentCreate(Contract):
    operation_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = Field(min_length=1, max_length=80)
    profile_id: str | None = Field(default=None, max_length=64)


class EnrollmentView(Contract):
    enrollment_id: str
    profile_id: str
    state: Literal["collecting", "ready", "cancelled", "expired"]
    accepted_samples: int
    expires_at: float


class SpeakerProfileView(Contract):
    profile_id: str
    display_name: str
    revision: int
    enrollment_id: str
    recording_available: bool = False


class PolicyUpdate(Contract):
    mode: Literal["off", "allowlist"]
    expected_revision: int = Field(ge=0)


class VoicePolicyView(Contract):
    companion_id: str
    mode: Literal["off", "allowlist"] = "off"
    revision: int = 0
    profiles: list[SpeakerProfileView] = Field(default_factory=list)
    allowed_profile_ids: list[str] = Field(default_factory=list)


class VoiceTemplate(Contract):
    profile_id: str
    revision: int
    sample: ExtractedSample


class VoicePolicySnapshot(Contract):
    companion_id: str
    owner_id: str
    mode: Literal["off", "allowlist"]
    revision: int
    templates: list[VoiceTemplate] = Field(default_factory=list)


class AdmissionRequest(Contract):
    revision: int = Field(ge=0)
    profile_id: str | None = None


class AdmissionResponse(Contract):
    allowed: bool


class VoiceAudioRequest(Contract):
    """Bounded mono 16-bit PCM at 16 kHz, base64 encoded for management relay."""

    pcm_base64: str = Field(min_length=4, max_length=1280000)


class SpeakerExtractionReadiness(Contract):
    """Numerical extraction readiness is never Companion admission readiness."""

    state: Literal['disabled', 'not_started', 'loading', 'ready', 'unavailable', 'closed']
    extraction_ready: bool
    # No calibrated admission implementation has been released yet.
    admission_ready: Literal[False] = False


class EnrollmentCompletion(Contract):
    """Trusted extraction and its optional original trial recording, published together."""

    sample: ExtractedSample
    recording: VoiceAudioRequest | None = None


class EnrollmentSampleRequest(VoiceAudioRequest):
    sample_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
