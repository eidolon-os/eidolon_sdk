"""Speaker identity evidence for one utterance, never an authentication or Memory grant.

Recognition produces calibrated evidence: for each compared Person a
log-likelihood ratio and an open-set posterior, plus the posterior that the
speaker is someone not enrolled. Each use of identity has its own threshold
(design §3.3); the observation records which Person, if any, meets it.
Consumers read the decision for their own use and never apply a threshold
of their own. Posteriors are calibrated estimates, not proof of identity.
"""

from typing import Literal

from pydantic import Field, model_validator

from .person import PersonProfile
from .voiceprint import Contract, SpeakerAudioQuality, VoiceTemplate

MAX_CANDIDATE_PERSONS = 20
MAX_RECOGNITION_PERSONS = 25
MAX_EVIDENCE = 5

PERSON_USES = ("personal_memory", "addressing", "speaker_label", "candidate_evidence")


def channel_class(device_kind: str | None) -> str:
    """The capture channel a calibration distinguishes: every phone app is one channel."""
    if not device_kind:
        return "unknown"
    return "mobile" if device_kind.startswith("eidolon-mobile") else device_kind


class SpeakerEvidenceSource(Contract):
    request_id: str = Field(min_length=1, max_length=128)
    session_id: str | None = None
    input_id: str = Field(min_length=1, max_length=128)
    generation: int = Field(ge=0)
    sample_rate: int = Field(gt=0)
    start_sample: int = Field(ge=0)
    end_sample: int = Field(gt=0)
    channel: str = Field(min_length=1, max_length=96)

    @model_validator(mode="after")
    def ordered_range(self):
        if self.end_sample <= self.start_sample:
            raise ValueError("nonempty source range required")
        return self


class PersonEvidence(Contract):
    person_id: str = Field(min_length=1, max_length=64)
    person_revision: int = Field(ge=1)
    maturity: Literal["candidate", "established"]
    is_named: bool
    profile_id: str = Field(min_length=1, max_length=64)
    profile_revision: int = Field(ge=1)
    llr: float = Field(allow_inf_nan=False)
    posterior: float = Field(ge=0, le=1, allow_inf_nan=False)


class IdentityDecisions(Contract):
    """Which Person meets each use's threshold; ``discovery``: likely someone not enrolled."""
    personal_memory: str | None = None
    addressing: str | None = None
    speaker_label: str | None = None
    candidate_evidence: str | None = None
    discovery: bool = False

    def persons(self) -> set[str]:
        return {p for p in (getattr(self, use) for use in PERSON_USES) if p is not None}


class SpeakerIdentityObservation(Contract):
    schema_version: Literal[2] = 2
    # Reserved subject/modality boundary: face evidence has no speaker
    # association in this release and must never enter signed turn identity.
    subject_role: Literal["speaker"] = "speaker"
    modalities: list[Literal["voice"]] = Field(default_factory=lambda: ["voice"], min_length=1, max_length=1)
    # compared: evidence was computed; otherwise ``reason`` says why not.
    status: Literal["compared", "uncertain", "unavailable"]
    reason: str = Field(min_length=1, max_length=128)
    owner_id: str = Field(min_length=1)
    source: SpeakerEvidenceSource | None = None
    session_id: str = Field(default="", max_length=128)
    turn_id: str = Field(default="", max_length=128)
    issued_at: float = Field(default=0, ge=0, allow_inf_nan=False)
    expires_at: float = Field(default=0, ge=0, allow_inf_nan=False)
    model_id: str | None = None
    weights_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str | None = None
    backend_version: str | None = None
    policy_version: str | None = None
    evidence: list[PersonEvidence] = Field(default_factory=list, max_length=MAX_EVIDENCE)
    posterior_unknown: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    decisions: IdentityDecisions = Field(default_factory=IdentityDecisions)
    display_name: str | None = Field(default=None, max_length=128)
    profile: PersonProfile | None = None
    audio_quality: SpeakerAudioQuality | None = None

    @model_validator(mode="after")
    def consistent_evidence(self):
        if self.source is not None and self.source.session_id is not None:
            if self.source.session_id != self.session_id:
                raise ValueError("observation must address its evidence session")
        if self.status == "compared":
            if self.source is None:
                raise ValueError("compared evidence requires an audio source")
            if self.posterior_unknown is None or not all((
                self.model_id, self.weights_hash, self.preprocessing_version,
                self.backend_version, self.policy_version,
            )):
                raise ValueError("compared evidence requires its versions and posteriors")
            if len({e.person_id for e in self.evidence}) != len(self.evidence):
                raise ValueError("one evidence entry per Person")
            if sum(e.posterior for e in self.evidence) + self.posterior_unknown > 1 + 1e-6:
                raise ValueError("posteriors exceed one")
        elif self.evidence or self.posterior_unknown is not None or self.decisions != IdentityDecisions():
            raise ValueError("only compared evidence can carry posteriors or decisions")
        compared = {e.person_id: e for e in self.evidence}
        if not self.decisions.persons() <= compared.keys():
            raise ValueError("a decision must name a compared Person")
        if self.decisions.discovery and self.decisions.persons():
            raise ValueError("a voice cannot be both a known Person and someone new")
        chosen = self.decisions.candidate_evidence
        if chosen is not None and compared[chosen].maturity != "candidate":
            raise ValueError("candidate evidence must name a candidate")
        if (self.display_name is not None or self.profile is not None) and self.decisions.addressing is None:
            raise ValueError("personal details accompany only an addressing decision")
        return self

    def decided(self, use: str) -> PersonEvidence | None:
        """The evidence of the Person meeting ``use``, if any."""
        person = getattr(self.decisions, use)
        return next((e for e in self.evidence if e.person_id == person), None) if person else None


class SpeakerCandidate(Contract):
    maturity: Literal["candidate", "established"] = "established"
    is_named: bool = True
    person_id: str = Field(min_length=1, max_length=64)
    person_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=128)
    profile: PersonProfile
    templates: list[VoiceTemplate] = Field(min_length=1, max_length=5)


class IdentityPolicy(Contract):
    """Delivered with the model: how calibrated evidence becomes per-use decisions."""
    version: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    weights_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str = Field(min_length=1, max_length=128)
    backend_version: str = Field(min_length=1, max_length=128)
    min_speech_ms: int = Field(ge=300, le=30000)
    # Below this, failing to match is not evidence of someone new.
    min_unknown_speech_ms: int = Field(ge=300, le=30000)
    prior_unknown: float = Field(gt=0, lt=1, allow_inf_nan=False)
    # Posterior thresholds; ``discovery`` applies to the posterior of someone not enrolled.
    personal_memory: float = Field(ge=0.5, lt=1, allow_inf_nan=False)
    addressing: float = Field(ge=0.5, lt=1, allow_inf_nan=False)
    speaker_label: float = Field(ge=0.5, lt=1, allow_inf_nan=False)
    candidate_evidence: float = Field(ge=0.5, lt=1, allow_inf_nan=False)
    discovery: float = Field(ge=0.5, lt=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def unknown_requires_sufficient_speech(self):
        if self.min_unknown_speech_ms < self.min_speech_ms:
            raise ValueError("unknown speech floor cannot be below extraction floor")
        return self


class CandidateDiscoveryPolicy(Contract):
    """Discovery is enabled for observations decided under this identity policy."""
    version: str = Field(min_length=1, max_length=128)
    identity_policy_version: str = Field(min_length=1, max_length=128)


class SpeakerCandidates(Contract):
    discovery_policy: CandidateDiscoveryPolicy | None = None
    owner_id: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    persons: list[SpeakerCandidate] = Field(default_factory=list, max_length=MAX_RECOGNITION_PERSONS)
