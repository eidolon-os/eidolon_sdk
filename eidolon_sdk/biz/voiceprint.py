"""Person-owned voiceprint management and numerical wire contracts, independent of inference."""

from __future__ import annotations

import math
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedSample(Contract):
    model_id: str = Field(min_length=1, max_length=128)
    weights_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str = Field(min_length=1, max_length=128)
    vector: list[float] = Field(min_length=2, max_length=2048)
    speech_ms: int = Field(ge=200, le=30000)
    quality: dict[str, float] = Field(default_factory=dict)

    @field_validator("vector")
    @classmethod
    def valid_vector(cls, value):
        if not all(math.isfinite(x) for x in value):
            raise ValueError("non-finite embedding")
        norm = math.hypot(*value)
        if not math.isfinite(norm) or norm < 1e-8:
            raise ValueError("empty embedding")
        return value if abs(norm - 1) < 1e-12 else [x / norm for x in value]

    @field_validator("quality")
    @classmethod
    def valid_quality(cls, value):
        if len(value) > 16 or any(len(k) > 64 or not math.isfinite(v) for k, v in value.items()):
            raise ValueError("invalid quality measurements")
        return value


class EnrollmentCreate(Contract):
    person_id: str = Field(min_length=1, max_length=64)
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
    person_id: str = Field(min_length=1, max_length=64)
    profile_id: str
    display_name: str
    revision: int
    enrollment_id: str
    recording_available: bool = False
    validation_state: Literal["unvalidated", "validated"] = "unvalidated"


class VoiceTemplate(Contract):
    profile_id: str
    revision: int
    sample: ExtractedSample


class VoiceAudioRequest(Contract):
    """Bounded mono 16-bit PCM at 16 kHz, base64 encoded for management relay."""

    pcm_base64: str = Field(min_length=4, max_length=1280000)


class SpeakerExtractionRequest(VoiceAudioRequest):
    """Internal extraction purpose; registration retains its longer quality floor."""
    purpose: Literal["enrollment"] = "enrollment"


class SpeakerAdmissionLimits(Contract):
    """Published release limits for conversation, distinct from recording UX."""

    max_allowed_speakers: int = Field(ge=1, le=5)
    min_audio_ms: int = Field(ge=300, le=30000)
    max_audio_ms: int = Field(ge=1500, le=30000)

    @model_validator(mode="after")
    def ordered_audio_range(self):
        if self.min_audio_ms > self.max_audio_ms:
            raise ValueError("valid admission audio range required")
        return self


class SpeakerExtractionReadiness(Contract):
    """Numerical extraction readiness; never conversation authorization."""
    state: Literal["disabled", "not_started", "loading", "ready", "unavailable", "closed"]
    extraction_ready: bool


class EnrollmentEvidence(Contract):
    """Internal owner-authorized snapshot, never returned to a Mobile client."""

    enrollment: EnrollmentView
    samples: dict[str, ExtractedSample]


def enrollment_evidence_digest(samples: dict[str, ExtractedSample]) -> str:
    payload = {key: value.model_dump(mode="json") for key, value in samples.items()}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class EnrollmentEvaluationRequest(Contract):
    samples: dict[str, ExtractedSample] = Field(min_length=3, max_length=3)
    trial: ExtractedSample
    recording_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EnrollmentEvaluation(Contract):
    """Versioned numerical preparation, explicitly not calibrated identity approval."""

    version: Literal["continuous-enrollment-v1"] = "continuous-enrollment-v1"
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    recording_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    template: ExtractedSample
    trial: ExtractedSample
    registration_min_similarity: float = Field(ge=-1, le=1)
    trial_min_similarity: float = Field(ge=-1, le=1)
    validation_state: Literal["unvalidated"] = "unvalidated"


class EnrollmentCompletion(Contract):
    """Trusted evaluation bound to the exact registration and replay recording."""

    evaluation: EnrollmentEvaluation
    recording: VoiceAudioRequest


class EnrollmentSampleRequest(VoiceAudioRequest):
    sample_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class SpeakerComparisonRequest(Contract):
    """Internal numerical request. Only the authority supplies templates."""

    probe: ExtractedSample
    templates: list[VoiceTemplate] = Field(min_length=1, max_length=5)

    @field_validator("templates")
    @classmethod
    def unique_profiles(cls, value):
        if len({t.profile_id for t in value}) != len(value):
            raise ValueError("duplicate profile")
        return value


class SpeakerSimilarity(Contract):
    profile_id: str
    revision: int
    status: Literal["scored", "incompatible"]
    similarity: float | None = Field(default=None, ge=-1, le=1)
    display_name: str = ""

    @model_validator(mode="after")
    def score_matches_status(self):
        if (self.status == "scored") != (self.similarity is not None):
            raise ValueError("score and status disagree")
        return self


class SpeakerComparisonResult(Contract):
    """No identity verdict, threshold or embedding is exposed by comparison."""

    validation_state: Literal["unvalidated"] = "unvalidated"
    scoring_version: Literal["normalized-template-cosine-v1"] = "normalized-template-cosine-v1"
    model_id: str
    weights_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str
    scores: list[SpeakerSimilarity] = Field(min_length=1, max_length=5)


class VoiceMatchTestResult(SpeakerComparisonResult):
    person_id: str
    person_revision: int
    audio_ms: int = Field(ge=1500, le=30000)
    extraction_ms: float = Field(ge=0)
    elapsed_ms: float = Field(ge=0)


class VoiceprintCollection(Contract):
    profiles: list[SpeakerProfileView] = Field(default_factory=list)
    readiness: SpeakerExtractionReadiness | None = None

class PersonVoiceTemplates(Contract):
    owner_id: str
    person_id: str
    person_revision: int = Field(ge=1)
    templates: list[VoiceTemplate] = Field(default_factory=list)
