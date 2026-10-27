"""Frozen model release contract shared by Models/Channel, not personal authority.

A valid document is a deployment input, not evidence that calibration occurred.
Calibrated releases require evidence; controlled trials explicitly make no such claim.
"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .voiceprint import ExtractedSample, SpeakerAdmissionLimits


class SpeakerAdmissionCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    validation_state: Literal["calibrated", "controlled_trial"]
    calibration_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    weights_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str = Field(min_length=1, max_length=128)
    scoring_version: Literal["normalized-template-cosine-v1"] = "normalized-template-cosine-v1"
    threshold: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)
    max_allowed_speakers: int = Field(ge=1, le=5, strict=True)
    min_audio_ms: int = Field(ge=300, le=30000, strict=True)
    max_audio_ms: int = Field(ge=1500, le=30000, strict=True)
    registration_min_similarity: float = Field(ge=-1, le=1, allow_inf_nan=False, strict=True)
    trial_min_similarity: float = Field(ge=-1, le=1, allow_inf_nan=False, strict=True)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_duration(self):
        if self.validation_state == "calibrated" and self.evidence_sha256 is None:
            raise ValueError("calibrated release requires evidence")
        if self.min_audio_ms > self.max_audio_ms:
            raise ValueError("valid calibration audio range required")
        return self

    @property
    def limits(self) -> SpeakerAdmissionLimits:
        return SpeakerAdmissionLimits(
            max_allowed_speakers=self.max_allowed_speakers,
            min_audio_ms=self.min_audio_ms, max_audio_ms=self.max_audio_ms,
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()



    def compatible(self, sample: ExtractedSample) -> bool:
        return (sample.model_id, sample.weights_hash, sample.preprocessing_version) == (
            self.model_id,
            self.weights_hash,
            self.preprocessing_version,
        )


def load_calibration(path: str) -> SpeakerAdmissionCalibration:
    if not path:
        raise ValueError("SPEAKER_CALIBRATION_REQUIRED")
    try:
        with Path(path).expanduser().open("rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError("oversized calibration")
        return SpeakerAdmissionCalibration.model_validate_json(raw)
    except (OSError, ValueError):
        # Never echo an artifact or unrelated file contents into a session log.
        raise ValueError("SPEAKER_CALIBRATION_INVALID") from None
