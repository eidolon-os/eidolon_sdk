"""Shared semantic persona genome contracts.

The genome is an immutable, model-independent description of who a companion
is.  It deliberately does not contain prompt templates or trait-to-instruction
mappings.  Runtime projects may *realize* the same genome differently for text,
voice, or an embodied device without changing the sovereign persona asset.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PERSONA_GENOME_SCHEMA = "eidolon.persona_genome"
PERSONA_REALIZER = "eidolon.persona_realizer"

RelationshipStage = Literal["new", "familiar", "trusted", "deep"]

DEFAULT_PERSONA_VALUES = (
    "温暖而不空泛",
    "诚实说明不确定性",
    "尊重 owner 的主权和最终选择",
)
DEFAULT_PERSONA_BOUNDARIES = (
    "不假装记得未提供或没有证据的事实",
    "明确遵守安全与隐私边界",
)
DEFAULT_PERSONA_BEHAVIOR_GUIDANCE = (
    "先回应 owner 当前的意图，再补充建议。",
    "让记忆形成连续性，但不编造记忆。",
)


class PersonaTraitState(BaseModel):
    """An observable evolution coordinate, not a prompt instruction."""

    model_config = ConfigDict(extra="forbid")

    value: float = Field(0.5, ge=0.0, le=1.0)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    last_changed_at: datetime | None = None
    source: str = "template"


class PersonaEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref_id: str
    summary: str = ""
    confidence: float = Field(0.5, ge=0.0, le=1.0)


class PersonaConstitution(BaseModel):
    """Stable identity and owner-governed hard boundaries."""

    model_config = ConfigDict(extra="forbid")

    name: str
    archetype: str = "companion"
    self_concept: str = ""
    values: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)


class PersonaCharacter(BaseModel):
    """Rich character meaning plus measurable, non-executable traits."""

    model_config = ConfigDict(extra="forbid")

    portrait: str = ""
    traits: dict[str, PersonaTraitState] = Field(default_factory=dict)
    tensions: list[str] = Field(default_factory=list)
    growth_edges: list[str] = Field(default_factory=list)


class PersonaRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: RelationshipStage = "new"
    narrative: str = ""
    commitments: list[str] = Field(default_factory=list)
    pinned_facts: list[str] = Field(default_factory=list)
    owner_preferences: dict[str, Any] = Field(default_factory=dict)
    safety_boundaries: list[str] = Field(default_factory=list)


class PersonaExpression(BaseModel):
    """Authored expression, examples, and modality nuance.

    These fields describe a coherent voice.  They are not a compiler DSL and
    are consumed holistically by the runtime realizer.
    """

    model_config = ConfigDict(extra="forbid")

    voice_portrait: str = ""
    behavior_guidance: list[str] = Field(default_factory=list)
    dialogue_examples: list[str] = Field(default_factory=list)
    modality_notes: dict[str, str] = Field(default_factory=dict)
    signature_phrases: dict[str, str] = Field(default_factory=dict)


class PersonaMemoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recall_policy: dict[str, Any] = Field(default_factory=dict)
    relation_policies: dict[str, Any] = Field(default_factory=dict)


class PersonaEvolutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    auto_apply_low_risk: bool = True
    max_delta_per_commit: float = Field(0.05, ge=0.0, le=1.0)
    review_required_traits: list[str] = Field(default_factory=list)


class PersonaProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")

    origin: str = "template"
    base_genome_id: str | None = None
    evidence_refs: list[PersonaEvidenceRef] = Field(default_factory=list)


class PersonaGenome(BaseModel):
    """Immutable semantic persona snapshot stored by ``eidolon_data``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["eidolon.persona_genome"] = PERSONA_GENOME_SCHEMA
    constitution: PersonaConstitution
    character: PersonaCharacter = Field(default_factory=PersonaCharacter)
    relationship: PersonaRelationship = Field(default_factory=PersonaRelationship)
    expression: PersonaExpression = Field(default_factory=PersonaExpression)
    memory_policy: PersonaMemoryPolicy = Field(default_factory=PersonaMemoryPolicy)
    evolution_policy: PersonaEvolutionPolicy = Field(default_factory=PersonaEvolutionPolicy)
    provenance: PersonaProvenance = Field(default_factory=PersonaProvenance)

    @model_validator(mode="after")
    def _ensure_named_identity(self) -> "PersonaGenome":
        if not self.constitution.name.strip():
            raise ValueError("persona genome constitution.name is required")
        return self


class PersonaAuthoringDraft(BaseModel):
    """Open authoring input used by Admin before a canonical genome exists."""

    model_config = ConfigDict(extra="forbid")

    name: str
    archetype: str = "companion"
    self_concept: str = ""
    character_portrait: str = "一个沉稳、专注、愿意长期理解 owner 的伙伴。"
    relationship_narrative: str = ""
    voice_portrait: str = "温暖、清晰、具体，不用空泛语言填补回应。"
    values: list[str] = Field(default_factory=lambda: list(DEFAULT_PERSONA_VALUES))
    boundaries: list[str] = Field(default_factory=lambda: list(DEFAULT_PERSONA_BOUNDARIES))
    commitments: list[str] = Field(default_factory=list)
    pinned_facts: list[str] = Field(default_factory=list)
    safety_boundaries: list[str] = Field(default_factory=list)
    behavior_guidance: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PERSONA_BEHAVIOR_GUIDANCE)
    )
    dialogue_examples: list[str] = Field(default_factory=list)
    modality_notes: dict[str, str] = Field(default_factory=dict)
    traits: dict[str, PersonaTraitState] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ensure_name(self) -> "PersonaAuthoringDraft":
        if not self.name.strip():
            raise ValueError("persona authoring draft name is required")
        return self


class PersonaObservationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    owner_id: str
    companion_id: str
    kind: str
    source: str = "system"
    summary: str = ""
    strength: float = Field(0.5, ge=0.0, le=1.0)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    evidence_refs: list[PersonaEvidenceRef] = Field(default_factory=list)
    created_at: datetime | None = None


class PersonaEvolutionProposalEvent(BaseModel):
    """A complete candidate snapshot grounded in explicit evidence.

    Evolution is intentionally snapshot-based. It does not expose a field
    mapping language that lets runtime code mechanically translate traits into
    prompt instructions.
    """

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    owner_id: str
    companion_id: str
    base_genome_id: str
    base_genome_hash: str
    proposed_genome_id: str
    status: Literal["pending", "approved", "rejected"] = "pending"
    risk: Literal["low", "medium", "high"] = "low"
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    rationale: str = ""
    proposed_genome: PersonaGenome
    evidence_refs: list[PersonaEvidenceRef] = Field(default_factory=list)
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _ensure_lineage(self) -> "PersonaEvolutionProposalEvent":
        if self.proposed_genome.provenance.base_genome_id != self.base_genome_id:
            raise ValueError("proposed genome provenance must reference base_genome_id")
        if not self.evidence_refs:
            raise ValueError("persona evolution proposal requires evidence")
        return self


class ResolvedRuntimeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    owner_id: str
    companion_id: str
    memory_realm_id: str
    genome_id: str
    genome_hash: str
    realizer_version: str
    device_id: str | None = None
    interaction_mode: str | None = None

    @classmethod
    def from_resolve_response(cls, data: dict[str, Any]) -> "ResolvedRuntimeIdentity":
        context = data.get("context")
        if not isinstance(context, dict):
            raise ValueError("admin resolve response missing context")
        return cls.model_validate(context)


def _default_traits() -> dict[str, PersonaTraitState]:
    return {
        "core.extraversion": PersonaTraitState(value=0.5),
        "core.intimacy": PersonaTraitState(value=0.35),
        "core.vulnerability": PersonaTraitState(value=0.25),
        "core.structure": PersonaTraitState(value=0.55),
        "core.directiveness": PersonaTraitState(value=0.45),
        "core.grounding": PersonaTraitState(value=0.65),
        "core.imagination": PersonaTraitState(value=0.55),
        "core.playfulness": PersonaTraitState(value=0.5),
        "core.reflection_depth": PersonaTraitState(value=0.55),
    }


def build_default_persona_genome(
    *,
    name: str,
    archetype: str = "companion",
    origin: str = "template",
    base_genome_id: str | None = None,
) -> PersonaGenome:
    return PersonaGenome(
        constitution=PersonaConstitution(
            name=name,
            archetype=archetype or "companion",
            values=list(DEFAULT_PERSONA_VALUES),
            boundaries=list(DEFAULT_PERSONA_BOUNDARIES),
        ),
        character=PersonaCharacter(
            portrait="一个沉稳、专注、愿意长期理解 owner 的伙伴。",
            traits=_default_traits(),
        ),
        expression=PersonaExpression(
            voice_portrait="温暖、清晰、具体，不用空泛语言填补回应。",
            behavior_guidance=list(DEFAULT_PERSONA_BEHAVIOR_GUIDANCE),
        ),
        memory_policy=PersonaMemoryPolicy(
            recall_policy={"scope": "owner_companion", "use_memory_as_evidence": True},
        ),
        evolution_policy=PersonaEvolutionPolicy(
            enabled=True,
            auto_apply_low_risk=True,
            max_delta_per_commit=0.05,
            review_required_traits=["core.intimacy", "core.vulnerability"],
        ),
        provenance=PersonaProvenance(origin=origin, base_genome_id=base_genome_id),
    )


def build_persona_genome_from_draft(
    draft: PersonaAuthoringDraft,
    *,
    origin: str = "owner_authored",
    base_genome_id: str | None = None,
) -> PersonaGenome:
    """Create one coherent snapshot without interpreting prose as other fields."""

    base = build_default_persona_genome(
        name=draft.name.strip(),
        archetype=draft.archetype,
        origin=origin,
        base_genome_id=base_genome_id,
    )
    return base.model_copy(
        update={
            "constitution": base.constitution.model_copy(
                update={
                    "self_concept": draft.self_concept.strip(),
                    "values": list(draft.values),
                    "boundaries": list(draft.boundaries),
                }
            ),
            "character": base.character.model_copy(
                update={
                    "portrait": draft.character_portrait.strip(),
                    "traits": {**base.character.traits, **draft.traits},
                }
            ),
            "relationship": PersonaRelationship(
                narrative=draft.relationship_narrative.strip(),
                commitments=list(draft.commitments),
                pinned_facts=list(draft.pinned_facts),
                safety_boundaries=list(draft.safety_boundaries),
            ),
            "expression": PersonaExpression(
                voice_portrait=draft.voice_portrait.strip(),
                behavior_guidance=list(draft.behavior_guidance),
                dialogue_examples=list(draft.dialogue_examples),
                modality_notes=dict(draft.modality_notes),
            ),
        }
    )


def normalize_persona_genome(
    genome_json: dict[str, Any] | PersonaGenome | None,
) -> PersonaGenome:
    if isinstance(genome_json, PersonaGenome):
        return genome_json
    if not genome_json:
        raise ValueError("persona genome payload is required")
    if genome_json.get("schema_version") != PERSONA_GENOME_SCHEMA:
        raise ValueError(
            f"unsupported persona genome schema: {genome_json.get('schema_version')!r}; "
            f"expected {PERSONA_GENOME_SCHEMA!r}"
        )
    return PersonaGenome.model_validate(genome_json)


def persona_genome_to_json(genome: PersonaGenome) -> dict[str, Any]:
    return genome.model_dump(mode="json", exclude_none=True)


def canonical_persona_genome_json(genome: PersonaGenome | dict[str, Any]) -> str:
    model = genome if isinstance(genome, PersonaGenome) else PersonaGenome.model_validate(genome)
    return json.dumps(persona_genome_to_json(model), sort_keys=True, separators=(",", ":"))


def persona_genome_hash(genome: PersonaGenome | dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_persona_genome_json(genome).encode("utf-8")).hexdigest()
    return f"pg_{digest[:32]}"


def runtime_manifest_hash(manifest: str) -> str:
    digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    return f"manifest_{digest[:32]}"


#: Why a persona mutation was refused, in a word a consumer can act on.
#:
#: The refusals were all real and all indistinguishable: the authority raised
#: exceptions carrying English sentences, so anything across a process boundary
#: had to match on prose to tell "someone changed it while you were deciding"
#: from "that genome is not this Companion's". One of those is worth retrying
#: after a re-read and the other never is.
#:
#: Here rather than in the producer because the producer is not the only reader:
#: the code has to survive an HTTP hop and be understood identically by the
#: Agent, whose evolution path drives these commands, and by anything that later
#: relays a refusal to a person.
PersonaConflictCode = Literal[
    #: The proposal was written against a genome that is no longer current. The
    #: work is not wrong, it is just out of date — re-read and propose again.
    "base_not_current",
    #: The base genome id matches but its content does not. Same shape of
    #: staleness, caught by hash rather than by pointer, and worth its own code
    #: because it means something rewrote a genome in place.
    "base_hash_mismatch",
    #: The current genome moved between the proposal and its activation. The
    #: proposal is marked stale by the authority, so retrying *this* one cannot
    #: succeed.
    "current_changed",
    #: The genome is not in a state this command accepts — approving something
    #: already committed, rejecting something already rejected, rolling back to
    #: a proposal a Companion never became.
    "state_not_eligible",
    #: The genome exists but belongs to another Companion, or to nobody. Never a
    #: retry: it is a request about something that is not there.
    "not_this_companion",
    #: The Companion this command names does not exist.
    "companion_missing",
]

__all__ = [
    "PERSONA_GENOME_SCHEMA",
    "PersonaConflictCode",
    "PERSONA_REALIZER",
    "PersonaAuthoringDraft",
    "PersonaCharacter",
    "PersonaConstitution",
    "PersonaEvidenceRef",
    "PersonaEvolutionPolicy",
    "PersonaEvolutionProposalEvent",
    "PersonaExpression",
    "PersonaGenome",
    "PersonaMemoryPolicy",
    "PersonaObservationEvent",
    "PersonaProvenance",
    "PersonaRelationship",
    "PersonaTraitState",
    "ResolvedRuntimeIdentity",
    "build_default_persona_genome",
    "build_persona_genome_from_draft",
    "canonical_persona_genome_json",
    "normalize_persona_genome",
    "persona_genome_hash",
    "persona_genome_to_json",
    "runtime_manifest_hash",
]
