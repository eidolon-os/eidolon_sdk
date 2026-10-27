"""Optional OS speaker observation, never an authentication or Memory grant.

Consumers opt in for one evidence range. Numerical cosine scores are not
probabilities. No consumer or automatic per-turn inference is installed here.
"""

from typing import Literal
from pydantic import Field, model_validator
from .voiceprint import Contract


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
    source: SpeakerEvidenceSource
    person_id: str | None = None
    person_revision: int | None = Field(default=None, ge=1)
    profile_id: str | None = None
    profile_revision: int | None = Field(default=None, ge=1)
    model_id: str | None = None
    weights_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str | None = None
    scoring_version: str | None = None
    decision_version: str | None = None
    confidence: Literal["validated", "unvalidated", "none"]
    cosine_similarity: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def consistent_identity(self):
        identity = (self.person_id, self.person_revision, self.profile_id, self.profile_revision)
        if self.status == "identified":
            if not all(identity) or self.confidence != "validated":
                raise ValueError("identified requires a versioned Person and validated decision")
        elif any(value is not None for value in identity):
            raise ValueError("non-identified observations cannot assert a Person")
        if self.status in ("identified", "unknown"):
            if self.confidence != "validated" or not all(
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
