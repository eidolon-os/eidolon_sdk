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
    # A conversation track's sample is the plain mean of its segments' unit
    # vectors, and is calibrated as that mean. ``vector`` is always unit; this
    # is the mean's own length, so scoring can rebuild it (design §3.2).
    mean_length: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)

    @field_validator("vector")
    @classmethod
    def valid_vector(cls, value):
        if not all(math.isfinite(x) for x in value):
            raise ValueError("non-finite embedding")
        norm = math.hypot(*value)
        if not math.isfinite(norm) or norm < 1e-8:
            raise ValueError("empty embedding")
        return value if abs(norm - 1) < 1e-12 else [x / norm for x in value]

    @classmethod
    def track_mean(cls, vectors, speech_ms: int, *, model_id: str, weights_hash: str,
                   preprocessing_version: str) -> "ExtractedSample":
        """The sample of a track: the plain mean of its segments' unit vectors."""
        dims = {len(v) for v in vectors}
        if not vectors or len(dims) != 1:
            raise ValueError("a track mean needs segments of one dimension")
        mean = [math.fsum(column) / len(vectors) for column in zip(*vectors)]
        return cls(model_id=model_id, weights_hash=weights_hash,
                   preprocessing_version=preprocessing_version, vector=mean,
                   speech_ms=min(speech_ms, 30000), mean_length=min(1.0, math.hypot(*mean)))

    def scored_vector(self) -> list[float]:
        """The vector as the back-end was calibrated on it: a track's mean, or the unit vector."""
        return self.vector if self.mean_length is None else [x * self.mean_length for x in self.vector]

    @field_validator("quality")
    @classmethod
    def valid_quality(cls, value):
        if len(value) > 16 or any(len(k) > 64 or not math.isfinite(v) for k, v in value.items()):
            raise ValueError("invalid quality measurements")
        return value


class CalibrationCrop(Contract):
    """A voiced window of a registration recording, embedded like a conversation probe.

    Vectors are kept to six decimals; a cosine between two crops is accurate to
    about 1e-5, far below any decision margin.
    """

    speech_ms: int = Field(ge=300, le=30000)
    vector: list[float] = Field(min_length=2, max_length=2048)

    @field_validator("vector")
    @classmethod
    def unit_vector(cls, value):
        if not all(math.isfinite(x) for x in value):
            raise ValueError("non-finite embedding")
        norm = math.hypot(*value)
        if not math.isfinite(norm) or norm < 1e-8:
            raise ValueError("empty embedding")
        scale = 1 if abs(norm - 1) < 1e-4 else norm
        return [round(x / scale, 6) for x in value]


class EnrollmentSample(ExtractedSample):
    """A registration sample and windows of it, scored later like conversation probes."""

    # A plain sample (one stored before windows existed) is one with no windows.
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    crops: list[CalibrationCrop] = Field(default_factory=list, max_length=8)

    def sample(self) -> ExtractedSample:
        return ExtractedSample.model_validate(self.model_dump(exclude={"crops"}))


def _without_windows(value):
    # Templates, trials and probes are plain samples; windows belong to
    # registration evidence only, even when an in-process caller passes one.
    return value.sample() if isinstance(value, EnrollmentSample) else value


class GenuineScore(Contract):
    """One same-person score whose window never contributed to the template it was scored against."""

    speech_ms: int = Field(ge=300, le=30000)
    similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)


class TemplateCalibration(Contract):
    """Same-person evidence that registration provides for free; never a threshold itself."""

    version: Literal["enrollment-windows-v1"] = "enrollment-windows-v1"
    crops: list[CalibrationCrop] = Field(default_factory=list, max_length=32)
    genuine: list[GenuineScore] = Field(default_factory=list, max_length=32)


class EnrollmentCreate(Contract):
    person_id: str = Field(min_length=1, max_length=64)
    operation_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    profile_id: str | None = Field(default=None, max_length=64)


class EnrollmentView(Contract):
    enrollment_id: str
    profile_id: str
    state: Literal["collecting", "ready", "cancelled", "expired"]
    accepted_samples: int
    expires_at: float


class SpeakerProfileView(Contract):
    origin: Literal["enrollment", "observation"] = "enrollment"
    source_observation_id: str | None = None
    person_id: str = Field(min_length=1, max_length=64)
    profile_id: str
    revision: int
    enrollment_id: str | None = None
    recording_available: bool = False
    validation_state: Literal["unvalidated", "validated"] = "unvalidated"


    @model_validator(mode="after")
    def provenance(self):
        if self.origin == "enrollment":
            if not self.enrollment_id or self.source_observation_id is not None:
                raise ValueError("enrollment profile requires only enrollment provenance")
        elif self.enrollment_id is not None or not self.source_observation_id:
            raise ValueError("observation profile requires only observation provenance")
        return self


# Registration captures only through the phone app, so registration
# templates share one calibration channel (see speaker_identity.channel_class).
REGISTRATION_CHANNEL = "mobile"


class VoiceTemplate(Contract):
    profile_id: str
    revision: int
    sample: ExtractedSample
    calibration: TemplateCalibration | None = None
    # The capture channel the template was built from; observation templates
    # carry the channel of the probe that created them.
    channel: str = Field(default=REGISTRATION_CHANNEL, min_length=1, max_length=96)

    @field_validator("sample", mode="before")
    @classmethod
    def plain_sample(cls, value):
        return _without_windows(value)


class VoiceAudioRequest(Contract):
    """Bounded mono 16-bit PCM at 16 kHz, base64 encoded for management relay."""

    pcm_base64: str = Field(min_length=4, max_length=1280000)


class VoiceCaptureSession(Contract):
    """Ephemeral microphone grant; credentials must never be persisted or logged."""
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    server_urls: list[str] = Field(min_length=1, max_length=16)
    token: str = Field(min_length=1)


class SpeakerExtractionRequest(VoiceAudioRequest):
    """Internal extraction purpose; registration retains its longer quality floor."""
    purpose: Literal["enrollment", "recognition"] = "enrollment"
    min_speech_ms: int = Field(default=1500, ge=300, le=30000)

    @model_validator(mode="after")
    def enrollment_quality_floor(self):
        if self.purpose == "enrollment" and self.min_speech_ms < 1500:
            raise ValueError("enrollment requires at least 1500 ms of speech")
        return self


class SpeakerAudioQuality(Contract):
    """Bounded diagnostics; never PCM, embeddings, or identity evidence."""
    audio_ms: int = Field(ge=0, le=30000)
    required_speech_ms: int = Field(ge=300, le=30000)
    speech_ms: int | None = Field(default=None, ge=0, le=30000)
    clipping: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    rms: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    overlap_detected: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)



class SpeakerExtractionReadiness(Contract):
    """Numerical extraction readiness; never conversation authorization."""
    state: Literal["disabled", "not_started", "loading", "ready", "unavailable", "closed"]
    extraction_ready: bool


class EnrollmentEvidence(Contract):
    """Internal owner-authorized snapshot, never returned to a Mobile client."""

    enrollment: EnrollmentView
    samples: dict[str, EnrollmentSample]


def _evidence(value: ExtractedSample) -> dict:
    # A sample without windows digests the same whichever type carries it.
    data = value.model_dump(mode="json")
    if not data.get("crops"):
        data.pop("crops", None)
    return data


def enrollment_evidence_digest(samples: dict[str, ExtractedSample]) -> str:
    payload = {key: _evidence(value) for key, value in samples.items()}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class EnrollmentEvaluationRequest(Contract):
    samples: dict[str, EnrollmentSample] = Field(min_length=3, max_length=3)
    trial: EnrollmentSample
    recording_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EnrollmentEvaluation(Contract):
    """Versioned numerical preparation, explicitly not calibrated identity approval."""

    version: Literal["continuous-enrollment-v1"] = "continuous-enrollment-v1"
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    recording_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    template: ExtractedSample
    trial: ExtractedSample
    validation_state: Literal["unvalidated"] = "unvalidated"
    calibration: TemplateCalibration | None = None

    @field_validator("template", "trial", mode="before")
    @classmethod
    def plain_samples(cls, value):
        return _without_windows(value)


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

    @field_validator("probe", mode="before")
    @classmethod
    def plain_probe(cls, value):
        return _without_windows(value)

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
