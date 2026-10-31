"""Optional OS speaker observation, never an authentication or Memory grant.

Consumers opt in for one evidence range. Numerical cosine scores are not
probabilities. No consumer or automatic per-turn inference is installed here.
"""

from typing import Literal
from pydantic import Field, model_validator
from .voiceprint import Contract, VoiceTemplate, SpeakerAudioQuality
from .person import PersonProfile


MAX_CANDIDATE_PERSONS = 20
MAX_RECOGNITION_PERSONS = 25


class SpeakerEvidenceSource(Contract):
    request_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = None
    input_id: str = Field(min_length=1, max_length=128)
    generation: int = Field(ge=0)
    sample_rate: int = Field(gt=0)
    start_sample: int = Field(ge=0)
    end_sample: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered_range(self):
        if self.end_sample <= self.start_sample:
            raise ValueError("nonempty source range required")
        return self


class SpeakerIdentityObservation(Contract):
    schema_version: Literal[1] = 1
    # Reserved subject/modality boundary: face evidence has no speaker
    # association in this release and must never enter signed turn identity.
    subject_role: Literal["speaker"] = "speaker"
    modalities: list[Literal["voice"]] = Field(default_factory=lambda: ["voice"], min_length=1, max_length=1)
    maturity: Literal["candidate", "established"] | None = None
    is_named: bool | None = None
    status: Literal["identified", "unknown", "uncertain", "unavailable"]
    owner_id: str = Field(min_length=1)
    source: SpeakerEvidenceSource | None = None
    session_id: str = Field(default="", max_length=128)
    turn_id: str = Field(default="", max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    profile: PersonProfile | None = None
    issued_at: float = Field(default=0, ge=0, allow_inf_nan=False)
    expires_at: float = Field(default=0, ge=0, allow_inf_nan=False)
    person_id: str | None = None
    person_revision: int | None = Field(default=None, ge=1)
    profile_id: str | None = None
    profile_revision: int | None = Field(default=None, ge=1)
    model_id: str | None = None
    weights_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str | None = None
    scoring_version: str | None = None
    decision_version: str | None = None
    confidence: Literal["validated", "controlled_trial", "unvalidated", "none"]
    cosine_similarity: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=128)
    audio_quality: SpeakerAudioQuality | None = None

    @model_validator(mode="after")
    def consistent_identity(self):
        if self.source is not None and self.source.session_id is not None:
            if self.source.session_id != self.session_id:
                raise ValueError("observation must address its evidence session")
        if self.status != "identified" and (self.maturity is not None or self.is_named is not None):
            raise ValueError("unresolved observations cannot assert Person lifecycle")
        identity = (self.person_id, self.person_revision, self.profile_id, self.profile_revision)
        if self.status == "identified":
            if not all(identity) or self.confidence not in {"validated", "controlled_trial"}:
                raise ValueError("identified requires a versioned Person and validated decision")
        elif any(value is not None for value in identity):
            raise ValueError("non-identified observations cannot assert a Person")
        if self.status != "identified" and (self.display_name is not None or self.profile is not None):
            raise ValueError("non-identified observations cannot carry personal details")
        if self.status in ("identified", "unknown"):
            if self.source is None:
                raise ValueError("identity decisions require audio evidence")
            if self.confidence not in {"validated", "controlled_trial"} or not all(
                (
                    self.model_id,
                    self.weights_hash,
                    self.preprocessing_version,
                    self.scoring_version,
                    self.decision_version,
                )
            ):
                raise ValueError("a conclusive result requires versioned validated evidence")
        return self


class SpeakerCandidate(Contract):
    maturity: Literal["candidate", "established"] = "established"
    is_named: bool = True
    person_id: str = Field(min_length=1, max_length=64)
    person_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=128)
    profile: PersonProfile
    templates: list[VoiceTemplate] = Field(min_length=1, max_length=5)


class DurationBand(Contract):
    """Voiced-speech range with its own per-Person threshold; it ends where the next begins."""
    name: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    min_speech_ms: int = Field(ge=300, le=30000)
    # Calibration never sets a threshold below the floor, whatever the cohort says.
    floor: float = Field(ge=0, le=1, allow_inf_nan=False)
    # The identified Person must lead every other Person by this much.
    margin: float = Field(gt=0, le=1, allow_inf_nan=False)


class CohortReference(Contract):
    """Impostor embeddings delivered beside the model: public speakers only, no user data."""
    path: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    speakers: int = Field(ge=1)


class RecognitionCalibration(Contract):
    """How each Person's thresholds are derived; the derivation itself is deterministic."""
    version: str = Field(min_length=1, max_length=128)
    max_false_accept: float = Field(gt=0, le=0.05, allow_inf_nan=False)
    # Below this share of a Person's own registration windows, a band only extends a track.
    min_genuine_acceptance: float = Field(gt=0, le=1, allow_inf_nan=False)
    min_genuine_scores: int = Field(ge=1, le=32)
    bands: list[DurationBand] = Field(min_length=1, max_length=6)
    cohort: CohortReference

    @model_validator(mode="after")
    def ascending_bands(self):
        starts = [band.min_speech_ms for band in self.bands]
        if starts != sorted(set(starts)) or len({b.name for b in self.bands}) != len(self.bands):
            raise ValueError("bands must have distinct names and ascending starts")
        return self

    def band(self, speech_ms: int) -> DurationBand | None:
        found = None
        for band in self.bands:
            if speech_ms >= band.min_speech_ms:
                found = band
        return found


class SpeakerRecognitionPolicy(Contract):
    """Explicit deployment trial, never an admission or memory permission."""
    version: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    weights_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str = Field(min_length=1, max_length=128)
    # Without calibration (or for a Person with no registration windows) these
    # fixed values decide; calibration replaces them per Person and band.
    threshold: float = Field(ge=0, le=1, allow_inf_nan=False)
    min_person_margin: float = Field(gt=0, le=1, allow_inf_nan=False)
    min_speech_ms: int = Field(ge=300, le=30000)
    min_unknown_speech_ms: int = Field(default=1500, ge=300, le=30000)
    confidence: Literal["controlled_trial"] = "controlled_trial"
    calibration: RecognitionCalibration | None = None

    @model_validator(mode="after")
    def unknown_requires_sufficient_speech(self):
        if self.min_unknown_speech_ms < self.min_speech_ms:
            raise ValueError("unknown speech floor cannot be below extraction floor")
        if self.calibration is not None and self.calibration.bands[0].min_speech_ms != self.min_speech_ms:
            raise ValueError("calibrated bands must start at the extraction floor")
        return self


class CandidateDiscoveryPolicy(Contract):
    version: str = Field(min_length=1, max_length=128)
    # Match thresholds retain their existing authority and meaning.
    recognition: SpeakerRecognitionPolicy
    max_existing_similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)

    @model_validator(mode='after')
    def separated_from_match(self):
        if self.max_existing_similarity >= self.recognition.threshold - self.recognition.min_person_margin:
            raise ValueError('new identity requires a separate exclusion margin')
        return self


class SpeakerCandidates(Contract):
    discovery_policy: CandidateDiscoveryPolicy | None = None
    owner_id: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    persons: list[SpeakerCandidate] = Field(default_factory=list, max_length=MAX_RECOGNITION_PERSONS)
