"""Optional OS speaker observation, never an authentication or Memory grant.

Consumers opt in for one evidence range. Numerical cosine scores are not
probabilities. No consumer or automatic per-turn inference is installed here.
"""

from typing import Literal
from pydantic import Field, model_validator
from .voiceprint import Contract, VoiceTemplate
from .person import PersonProfile


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

    @model_validator(mode="after")
    def consistent_identity(self):
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
    person_id: str = Field(min_length=1, max_length=64)
    person_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=128)
    profile: PersonProfile
    templates: list[VoiceTemplate] = Field(min_length=1, max_length=5)


class SpeakerCandidates(Contract):
    owner_id: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    persons: list[SpeakerCandidate] = Field(default_factory=list, max_length=5)


class SpeakerRecognitionPolicy(Contract):
    """Explicit deployment trial, never an admission or memory permission."""
    version: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    weights_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str = Field(min_length=1, max_length=128)
    threshold: float = Field(ge=0, le=1, allow_inf_nan=False)
    min_person_margin: float = Field(gt=0, le=1, allow_inf_nan=False)
    min_speech_ms: int = Field(ge=1500, le=30000)
    confidence: Literal["controlled_trial"] = "controlled_trial"
