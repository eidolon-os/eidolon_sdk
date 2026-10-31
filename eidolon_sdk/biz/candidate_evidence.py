"""Bounded, service-submitted candidate observation receipts; never a grant."""
from typing import Literal

from pydantic import Field, model_validator

from .person import PersonContract
from .speaker_identity import CandidateDiscoveryPolicy as CandidateDiscoveryPolicy
from .speaker_identity import SpeakerIdentityObservation
from .voiceprint import ExtractedSample

CANDIDATE_MIN_SPEECH_MS = 1500
CANDIDATE_EVIDENCE_LIMIT = 5


class CandidateEvidence(PersonContract):
    policy_version: Literal['candidate-evidence-v1'] = 'candidate-evidence-v1'
    snapshot_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    audio_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    observation: SpeakerIdentityObservation

    @model_validator(mode='after')
    def independent_source(self):
        value = self.observation
        source = value.source
        if value.status != 'compared' or value.decided('candidate_evidence') is None:
            raise ValueError('candidate evidence requires a candidate meeting its use threshold')
        if not value.session_id or not value.turn_id or source is None:
            raise ValueError('candidate evidence requires session and turn')
        if source.session_id != value.session_id or source.request_id != value.turn_id:
            raise ValueError('candidate evidence source scope mismatch')
        if source.sample_rate != 16000:
            raise ValueError('candidate evidence requires canonical audio')
        if (value.audio_quality is None or value.audio_quality.speech_ms is None
                or value.audio_quality.speech_ms < CANDIDATE_MIN_SPEECH_MS):
            raise ValueError('insufficient independent speech')
        if value.audio_quality.overlap_detected != 0:
            raise ValueError('candidate evidence requires explicit non-overlap evidence')
        duration_ms = (source.end_sample - source.start_sample) * 1000 / source.sample_rate
        if value.audio_quality.speech_ms > duration_ms or duration_ms > 30000:
            raise ValueError('speech does not fit bounded source interval')
        if not 0 < value.expires_at - value.issued_at <= 10:
            raise ValueError('invalid evidence lifetime')
        return self


class CandidateEvidenceReceipt(PersonContract):
    maturity: Literal["candidate", "established"] = "candidate"
    person_revision: int = Field(ge=1)
    person_id: str
    accepted: bool
    independent_turns: int = Field(ge=0, le=CANDIDATE_EVIDENCE_LIMIT)


class CandidatePromotionPolicy(PersonContract):
    """Explicit model-bound trial policy; absent configuration disables promotion."""
    version: str = Field(min_length=1, max_length=128)
    # Evidence counts only when decided under this identity policy.
    identity_policy_version: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    weights_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    preprocessing_version: str = Field(min_length=1, max_length=128)
    min_turns: int = Field(default=3, ge=3, le=CANDIDATE_EVIDENCE_LIMIT)
    min_total_speech_ms: int = Field(default=4500, ge=4500, le=150000)
    # Each counted observation's posterior for the candidate.
    min_posterior: float = Field(ge=0.5, lt=1, allow_inf_nan=False)
    max_evidence_age_s: int = Field(default=604800, ge=60, le=604800)


class CandidateDiscovery(PersonContract):
    policy_version: str = Field(min_length=1, max_length=128)
    snapshot_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    audio_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    observation: SpeakerIdentityObservation
    sample: ExtractedSample

    @model_validator(mode='after')
    def valid_unknown_source(self):
        value, source = self.observation, self.observation.source
        if (value.status != 'compared' or not value.decisions.discovery
                or not value.session_id or not value.turn_id or source is None):
            raise ValueError('discovery requires scoped evidence of someone not enrolled')
        if source.session_id != value.session_id or source.request_id != value.turn_id or source.sample_rate != 16000:
            raise ValueError('discovery source scope mismatch')
        duration_ms = (source.end_sample - source.start_sample) * 1000 / source.sample_rate
        if not CANDIDATE_MIN_SPEECH_MS <= self.sample.speech_ms <= duration_ms <= 30000:
            raise ValueError('discovery requires sufficient bounded speech')
        if (self.sample.model_id, self.sample.weights_hash, self.sample.preprocessing_version) != (
                value.model_id, value.weights_hash, value.preprocessing_version):
            raise ValueError('sample does not match observation model')
        if value.audio_quality is None or value.audio_quality.speech_ms != self.sample.speech_ms:
            raise ValueError('sample does not match observation quality')
        if not 0 < value.expires_at - value.issued_at <= 10:
            raise ValueError('invalid discovery lifetime')
        # Missing overlap evaluation is not evidence of a single speaker.
        if self.sample.quality.get('overlap_detected') != 0:
            raise ValueError('discovery requires explicit non-overlap evidence')
        return self
