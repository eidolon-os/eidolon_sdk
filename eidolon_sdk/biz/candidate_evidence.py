"""Bounded, service-submitted candidate observation receipts; never a grant."""
from typing import Literal

from pydantic import Field, model_validator

from .person import PersonContract
from .speaker_identity import SpeakerIdentityObservation

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
        if value.status != 'identified' or value.maturity != 'candidate':
            raise ValueError('candidate evidence requires an identified candidate')
        if not value.session_id or not value.turn_id or source is None:
            raise ValueError('candidate evidence requires session and turn')
        if source.session_id != value.session_id or source.request_id != value.turn_id:
            raise ValueError('candidate evidence source scope mismatch')
        if source.sample_rate != 16000:
            raise ValueError('candidate evidence requires canonical audio')
        if (value.audio_quality is None or value.audio_quality.speech_ms is None
                or value.audio_quality.speech_ms < CANDIDATE_MIN_SPEECH_MS):
            raise ValueError('insufficient independent speech')
        duration_ms = (source.end_sample - source.start_sample) * 1000 / source.sample_rate
        if value.audio_quality.speech_ms > duration_ms or duration_ms > 30000:
            raise ValueError('speech does not fit bounded source interval')
        if not 0 < value.expires_at - value.issued_at <= 10:
            raise ValueError('invalid evidence lifetime')
        return self


class CandidateEvidenceReceipt(PersonContract):
    person_id: str
    accepted: bool
    independent_turns: int = Field(ge=0, le=CANDIDATE_EVIDENCE_LIMIT)
