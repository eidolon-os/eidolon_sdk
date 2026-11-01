"""Speaker identity evidence for one utterance, never an authentication or Memory grant.

Recognition produces calibrated evidence: for each compared Person a
log-likelihood ratio and an open-set posterior, plus the posterior that the
speaker is someone not enrolled. Each use of identity has its own threshold
in each comparison condition (design §3.3): registration happens on the
phone and speech arrives on every device, and how well one model separates
speakers differs by an order of magnitude between a phone template scored
against the phone and against a far-field device. The observation records
which Person, if any, meets each use's threshold.
Consumers read the decision for their own use and never apply a threshold
of their own. Posteriors are calibrated estimates, not proof of identity.
"""

from typing import Literal

from pydantic import Field, model_validator

from .person import PersonProfile
from .voiceprint import REGISTRATION_CHANNEL, Contract, SpeakerAudioQuality, VoiceTemplate

MAX_CANDIDATE_PERSONS = 20
MAX_RECOGNITION_PERSONS = 25
MAX_EVIDENCE = 5

PERSON_USES = ("personal_memory", "addressing", "speaker_label", "candidate_evidence")
# near_same: a phone template against the phone; far_same: a device's own
# observation template against that device; far_cross: anything else.
IDENTITY_CONDITIONS = ("near_same", "far_same", "far_cross")
IdentityCondition = Literal["near_same", "far_same", "far_cross"]


def channel_class(device_kind: str | None) -> str:
    """The capture channel a calibration distinguishes: every phone app is one channel."""
    if not device_kind:
        return "unknown"
    return "mobile" if device_kind.startswith("eidolon-mobile") else device_kind


def comparison_condition(template_channel: str, probe_channel: str) -> IdentityCondition:
    """Which calibration and thresholds a template-probe comparison falls under."""
    if template_channel != probe_channel or probe_channel == "unknown":
        return "far_cross"
    return "near_same" if probe_channel == REGISTRATION_CHANNEL else "far_same"


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


class VoiceRef(Contract):
    """A voice heard in one turn, by which attribution names it (design §3.5).

    ``turn_id`` is the Channel turn the observation was signed for; the Agent
    receives it as the turn's trace id. Every turn with audio evidence has one,
    whether or not anyone was recognised.
    """
    owner_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    # The conversation track (design §3.2); absent until tracks exist.
    track_id: str | None = Field(default=None, min_length=1, max_length=64)
    source: SpeakerEvidenceSource
    speech_ms: int = Field(ge=0, le=30000)

    @model_validator(mode="after")
    def scoped_source(self):
        if self.source.request_id != self.turn_id or self.source.session_id not in (None, self.session_id):
            raise ValueError("voice source must belong to its turn")
        return self

    def key(self) -> tuple[str, str, str]:
        return self.owner_id, self.session_id, self.turn_id


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
    # The conversation track the evidence continued (design §3.2), once tracks exist.
    track_id: str | None = Field(default=None, min_length=1, max_length=64)
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
    # The condition of the leading Person's comparison, whose thresholds decided.
    condition: IdentityCondition | None = None
    decisions: IdentityDecisions = Field(default_factory=IdentityDecisions)
    display_name: str | None = Field(default=None, max_length=128)
    profile: PersonProfile | None = None
    audio_quality: SpeakerAudioQuality | None = None

    @model_validator(mode="after")
    def consistent_evidence(self):
        if self.source is not None and self.source.session_id is not None:
            if self.source.session_id != self.session_id:
                raise ValueError("observation must address its evidence session")
        if self.track_id is not None and self.source is None:
            raise ValueError("a track continues only on audio evidence")
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
        elif (self.evidence or self.posterior_unknown is not None or self.condition is not None
              or self.decisions != IdentityDecisions()):
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

    def voice_ref(self) -> VoiceRef | None:
        """The voice this turn heard, when there is audio evidence with measured speech."""
        speech_ms = self.audio_quality.speech_ms if self.audio_quality is not None else None
        if self.source is None or speech_ms is None or not (self.session_id and self.turn_id):
            return None
        return VoiceRef(owner_id=self.owner_id, session_id=self.session_id, turn_id=self.turn_id,
                        track_id=self.track_id, source=self.source, speech_ms=speech_ms)


class SpeakerCandidate(Contract):
    maturity: Literal["candidate", "established"] = "established"
    is_named: bool = True
    person_id: str = Field(min_length=1, max_length=64)
    person_revision: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=128)
    profile: PersonProfile
    templates: list[VoiceTemplate] = Field(min_length=1, max_length=5)


class UseThresholds(Contract):
    """Posterior thresholds in one condition; ``discovery`` applies to the posterior
    of someone not enrolled. A use without a threshold is off in that condition:
    nothing is decided for it (design §7.3 M2 — a use not yet shown to meet its
    false-acceptance limit there ships switched off)."""
    personal_memory: float | None = Field(ge=0.5, lt=1, allow_inf_nan=False)
    addressing: float | None = Field(ge=0.5, lt=1, allow_inf_nan=False)
    speaker_label: float | None = Field(ge=0.5, lt=1, allow_inf_nan=False)
    candidate_evidence: float | None = Field(ge=0.5, lt=1, allow_inf_nan=False)
    discovery: float | None = Field(ge=0.5, lt=1, allow_inf_nan=False)


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
    conditions: dict[IdentityCondition, UseThresholds]
    # Household guard (design §3.3 L7): when a member's registration windows,
    # scored against another member's phone template, reach a use's threshold,
    # that use in near_same needs an LLR this far above the highest of them.
    household_margin_llr: float = Field(ge=0, le=20, allow_inf_nan=False)

    @model_validator(mode="after")
    def complete(self):
        if self.min_unknown_speech_ms < self.min_speech_ms:
            raise ValueError("unknown speech floor cannot be below extraction floor")
        if set(self.conditions) != set(IDENTITY_CONDITIONS):
            raise ValueError("every comparison condition needs its thresholds")
        return self

    def thresholds(self, condition: IdentityCondition) -> UseThresholds:
        return self.conditions[condition]


class CandidateDiscoveryPolicy(Contract):
    """Discovery is enabled for observations decided under this identity policy."""
    version: str = Field(min_length=1, max_length=128)
    identity_policy_version: str = Field(min_length=1, max_length=128)


class SpeakerCandidates(Contract):
    discovery_policy: CandidateDiscoveryPolicy | None = None
    owner_id: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    persons: list[SpeakerCandidate] = Field(default_factory=list, max_length=MAX_RECOGNITION_PERSONS)
