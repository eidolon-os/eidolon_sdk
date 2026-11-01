"""Attribution: the Person a voice heard in some turns belongs to (design §3.5, decision 11).

Chains that act at once (reading personal memory, addressing, the phone's
feedback) read the turn's signed decisions. Chains that can settle later
(writing personal memory, labelling speakers in history, the anonymous pools,
observation templates) read attribution, which may come with the turn, after
evidence accumulates, or from the Owner.

Only recognition compares voices. It submits verdicts over its authenticated
service channel. Data checks each verdict against the snapshot it was made on
and against its own counting rules (sessions, gaps, turns, voiced speech, pool
limits), records the attribution, and never scores. The Agent and Memory act
only on attribution recorded by Data.
"""

from typing import Literal

from pydantic import Field, model_validator

from .speaker_identity import IdentityCondition, SpeakerIdentityObservation, VoiceRef
from .voiceprint import Contract, ExtractedSample

MAX_VERDICT_REFS = 100

VerdictKind = Literal["turn", "attribute", "merge", "discover", "promote"]
AttributionSource = Literal["turn", "accumulated", "owner"]


def _distinct_refs(owner_id: str, refs: list[VoiceRef]) -> None:
    keys = [ref.key() for ref in refs]
    if len(set(keys)) != len(keys):
        raise ValueError("one reference per turn")
    if any(ref.owner_id != owner_id for ref in refs):
        raise ValueError("references must belong to the Owner")


class VerdictEvidence(Contract):
    """What decided a verdict, under the policy the verdict names."""
    # Same-voice evidence for the named Person; absent when the voice is someone new.
    llr: float | None = Field(default=None, allow_inf_nan=False)
    posterior: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    posterior_unknown: float = Field(ge=0, le=1, allow_inf_nan=False)
    condition: IdentityCondition

    @model_validator(mode="after")
    def distribution(self):
        if (self.llr is None) != (self.posterior is None):
            raise ValueError("same-voice evidence needs both its LLR and posterior")
        if (self.posterior or 0) + self.posterior_unknown > 1 + 1e-6:
            raise ValueError("posteriors exceed one")
        return self


class VoiceVerdict(Contract):
    """One judgment by recognition about a voice; Data applies it or refuses it.

    - ``turn``: this turn's voice is ``person_id``, by its ``personal_memory``
      decision (see :func:`turn_verdict`). One reference.
    - ``attribute``: evidence accumulated over ``refs`` says ``person_id``.
      Re-checks of provisional sources are attribute verdicts too.
      ``from_person_id`` names the candidate whose voice it turned out to be,
      when the references are that candidate's.
    - ``merge``: candidate ``from_person_id`` is candidate ``person_id``.
    - ``discover``: ``refs`` are one voice unlike everyone known; ``sample``
      becomes the new candidate's template.
    - ``promote``: candidate ``person_id`` is a stable voice, distinct from
      everyone known.
    """
    schema_version: Literal[1] = 1
    kind: VerdictKind
    owner_id: str = Field(min_length=1)
    refs: list[VoiceRef] = Field(min_length=1, max_length=MAX_VERDICT_REFS)
    person_id: str | None = Field(default=None, min_length=1, max_length=64)
    person_revision: int | None = Field(default=None, ge=1)
    from_person_id: str | None = Field(default=None, min_length=1, max_length=64)
    evidence: VerdictEvidence
    # discover: the new candidate's template. turn, attribute: an observation
    # template for the device the voice was heard on (design §3.2), when the
    # evidence qualifies for one.
    sample: ExtractedSample | None = None
    sample_channel: str | None = Field(default=None, min_length=1, max_length=96)
    model_id: str = Field(min_length=1, max_length=128)
    weights_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_version: str = Field(min_length=1, max_length=128)
    backend_version: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    # The recognition snapshot compared against; once it changes, the verdict is void.
    snapshot_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    issued_at: float = Field(ge=0, allow_inf_nan=False)
    expires_at: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent(self):
        _distinct_refs(self.owner_id, self.refs)
        if not 0 < self.expires_at - self.issued_at <= 10:
            raise ValueError("invalid verdict lifetime")
        named = self.kind != "discover"
        if named != (self.person_id is not None and self.person_revision is not None):
            raise ValueError("only a discover verdict names no Person")
        if named != (self.evidence.llr is not None):
            raise ValueError("a verdict about a Person carries same-voice evidence")
        if self.kind == "merge":
            if self.from_person_id is None:
                raise ValueError("a merge names the candidate merged")
        elif self.kind != "attribute" and self.from_person_id is not None:
            raise ValueError("only attribute and merge verdicts move a candidate")
        if self.from_person_id is not None and self.from_person_id == self.person_id:
            raise ValueError("a voice cannot move to the Person it already is")
        if self.kind == "turn" and len(self.refs) != 1:
            raise ValueError("a turn verdict is about its own turn")
        if self.kind == "discover" and self.sample is None:
            raise ValueError("a new candidate needs its template")
        if self.kind in ("merge", "promote") and self.sample is not None:
            raise ValueError("merges and promotions carry no template")
        if (self.sample is None) != (self.sample_channel is None):
            raise ValueError("a template names its channel")
        if self.sample is not None:
            if (self.sample.model_id, self.sample.weights_hash, self.sample.preprocessing_version) != (
                    self.model_id, self.weights_hash, self.preprocessing_version):
                raise ValueError("template does not match the verdict's model")
            if self.sample_channel not in {ref.source.channel for ref in self.refs}:
                raise ValueError("a template comes from a channel the voice was heard on")
        return self


def turn_verdict(observation: SpeakerIdentityObservation, *, snapshot_revision: str,
                 sample: ExtractedSample | None = None) -> VoiceVerdict | None:
    """The turn's own attribution: its ``personal_memory`` decision, if it made one."""
    decided = observation.decided("personal_memory")
    ref = observation.voice_ref()
    if decided is None or ref is None or observation.condition is None:
        return None
    return VoiceVerdict(
        kind="turn", owner_id=observation.owner_id, refs=[ref],
        person_id=decided.person_id, person_revision=decided.person_revision,
        evidence=VerdictEvidence(llr=decided.llr, posterior=decided.posterior,
                                 posterior_unknown=observation.posterior_unknown,
                                 condition=observation.condition),
        sample=sample, sample_channel=ref.source.channel if sample is not None else None,
        model_id=observation.model_id, weights_hash=observation.weights_hash,
        preprocessing_version=observation.preprocessing_version,
        backend_version=observation.backend_version, policy_version=observation.policy_version,
        snapshot_revision=snapshot_revision,
        issued_at=observation.issued_at, expires_at=observation.expires_at,
    )


class VoiceAttribution(Contract):
    """Data's record that the voice in ``refs`` belongs to a Person.

    The Agent labels those turns' speaker with it; Memory extracts their
    personal facts into that Person's Realm. Revocation comes only from the
    Owner (deleting the Person, "don't remember"), and whatever was derived
    from a revoked attribution is withdrawn with it.
    """
    schema_version: Literal[1] = 1
    attribution_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=1)
    owner_id: str = Field(min_length=1)
    person_id: str = Field(min_length=1, max_length=64)
    person_revision: int = Field(ge=1)
    refs: list[VoiceRef] = Field(min_length=1, max_length=MAX_VERDICT_REFS)
    source: AttributionSource
    revoked: bool = False
    recorded_at: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def owned_refs(self):
        _distinct_refs(self.owner_id, self.refs)
        return self
