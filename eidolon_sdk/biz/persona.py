"""Shared persona genome contracts.

The database stores persona genomes as immutable JSON snapshots. This module
owns the wire/storage shape and the canonical hash so every project agrees on
what "the current genome" means without introducing trait definition tables.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PERSONA_GENOME_SCHEMA_VERSION = "eidolon.persona_genome.v1"
PERSONA_COMPILER_VERSION = "eidolon.persona_compiler.v1"


class PersonaTraitState(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: float = Field(0.5, ge=0.0, le=1.0)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    last_changed_at: datetime | None = None
    source: str = "template"


class PersonaIdentityCore(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""
    archetype: str = "companion"
    values: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)


class PersonaRelationship(BaseModel):
    model_config = ConfigDict(extra="allow")

    stage: str = "new"
    pinned_facts: list[str] = Field(default_factory=list)
    owner_preferences: dict[str, Any] = Field(default_factory=dict)
    safety_boundaries: list[str] = Field(default_factory=list)


class PersonaStyleCompilerV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    base_instructions: list[str] = Field(default_factory=list)
    trait_mappings: dict[str, Any] = Field(default_factory=dict)
    spoken_phrases: list[dict[str, str]] = Field(default_factory=list)


class PersonaMemoryAdapterV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    recall_policy: dict[str, Any] = Field(default_factory=dict)
    relation_policies: dict[str, Any] = Field(default_factory=dict)


class PersonaEvolutionPolicyV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    auto_apply_low_risk: bool = True
    max_delta_per_commit: float = Field(0.05, ge=0.0, le=1.0)
    review_required_traits: list[str] = Field(default_factory=list)


class PersonaProvenanceV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    origin: str = "template"
    base_genome_id: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


class PersonaGenomeV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["eidolon.persona_genome.v1"] = PERSONA_GENOME_SCHEMA_VERSION
    identity_core: PersonaIdentityCore = Field(default_factory=PersonaIdentityCore)
    relationship: PersonaRelationship = Field(default_factory=PersonaRelationship)
    traits: dict[str, PersonaTraitState] = Field(default_factory=dict)
    style_compiler: PersonaStyleCompilerV1 = Field(default_factory=PersonaStyleCompilerV1)
    memory_adapter: PersonaMemoryAdapterV1 = Field(default_factory=PersonaMemoryAdapterV1)
    evolution_policy: PersonaEvolutionPolicyV1 = Field(default_factory=PersonaEvolutionPolicyV1)
    provenance: PersonaProvenanceV1 = Field(default_factory=PersonaProvenanceV1)

    @model_validator(mode="after")
    def _ensure_named_identity(self) -> "PersonaGenomeV1":
        if not self.identity_core.name.strip():
            raise ValueError("persona genome identity_core.name is required")
        return self


class PersonaEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str
    ref_id: str
    summary: str = ""
    confidence: float = Field(0.5, ge=0.0, le=1.0)


class PersonaObservationEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

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


class PersonaEvolutionPatch(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    target: str
    delta: float | None = Field(default=None, ge=-1.0, le=1.0)
    value: Any = None
    rationale: str = ""


class PersonaEvolutionProposalEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    proposal_id: str
    owner_id: str
    companion_id: str
    base_genome_id: str
    base_genome_hash: str
    status: str = "pending"
    risk: str = "low"
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    rationale: str = ""
    patches: list[PersonaEvolutionPatch] = Field(default_factory=list)
    evidence_refs: list[PersonaEvidenceRef] = Field(default_factory=list)
    created_at: datetime | None = None


class ResolvedRuntimeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    owner_id: str
    companion_id: str
    memory_realm_id: str
    genome_id: str
    genome_hash: str
    compiler_version: str
    device_id: str | None = None
    interaction_mode: str | None = None


def build_default_persona_genome(
    *,
    name: str,
    archetype: str = "companion",
    origin: str = "template",
    base_genome_id: str | None = None,
) -> PersonaGenomeV1:
    return PersonaGenomeV1(
        identity_core=PersonaIdentityCore(
            name=name,
            archetype=archetype or "companion",
            values=["be warm", "be honest", "respect owner sovereignty"],
            boundaries=[
                "do not pretend to remember facts that were not provided",
                "keep safety and privacy boundaries explicit",
            ],
        ),
        relationship=PersonaRelationship(stage="new"),
        traits={
            "core.extraversion": PersonaTraitState(value=0.5),
            "core.intimacy": PersonaTraitState(value=0.35),
            "core.vulnerability": PersonaTraitState(value=0.25),
            "core.structure": PersonaTraitState(value=0.55),
            "core.directiveness": PersonaTraitState(value=0.45),
            "core.grounding": PersonaTraitState(value=0.65),
            "core.imagination": PersonaTraitState(value=0.55),
            "core.playfulness": PersonaTraitState(value=0.5),
            "core.reflection_depth": PersonaTraitState(value=0.55),
        },
        style_compiler=PersonaStyleCompilerV1(
            base_instructions=[
                "Warm, clear, and grounded.",
                "Respond to the owner's intent before adding suggestions.",
                "Let memory shape continuity, but never invent remembered facts.",
            ],
            trait_mappings={},
            spoken_phrases=[],
        ),
        memory_adapter=PersonaMemoryAdapterV1(
            recall_policy={"scope": "owner_companion", "use_memory_as_evidence": True},
            relation_policies={},
        ),
        evolution_policy=PersonaEvolutionPolicyV1(
            enabled=True,
            auto_apply_low_risk=True,
            max_delta_per_commit=0.05,
            review_required_traits=["core.intimacy", "core.vulnerability"],
        ),
        provenance=PersonaProvenanceV1(origin=origin, base_genome_id=base_genome_id),
    )


def normalize_persona_genome(
    genome_json: dict[str, Any] | PersonaGenomeV1 | None,
    *,
    name: str,
    archetype: str = "companion",
    origin: str = "template",
    base_genome_id: str | None = None,
) -> PersonaGenomeV1:
    if isinstance(genome_json, PersonaGenomeV1):
        return genome_json
    if not genome_json:
        return build_default_persona_genome(
            name=name,
            archetype=archetype,
            origin=origin,
            base_genome_id=base_genome_id,
        )
    data = dict(genome_json)
    if data.get("schema_version") == PERSONA_GENOME_SCHEMA_VERSION:
        if not data.get("identity_core"):
            data["identity_core"] = {"name": name, "archetype": archetype}
        return PersonaGenomeV1.model_validate(data)
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    style = data.get("style") if isinstance(data.get("style"), dict) else {}
    boundaries = data.get("boundaries") if isinstance(data.get("boundaries"), dict) else {}
    return PersonaGenomeV1(
        identity_core=PersonaIdentityCore(
            name=str(identity.get("name") or name),
            archetype=str(identity.get("archetype") or archetype or "companion"),
            values=[str(item) for item in identity.get("values") or []],
            boundaries=[str(item) for item in boundaries.get("rules") or []],
        ),
        traits={
            "core.playfulness": PersonaTraitState(value=_float01(style.get("playfulness"), 0.5)),
            "core.structure": PersonaTraitState(value=_float01(style.get("structure"), 0.55)),
        },
        style_compiler=PersonaStyleCompilerV1(
            base_instructions=[
                item for item in (
                    f"Tone: {style.get('tone')}" if style.get("tone") else "",
                    f"Initiative: {style.get('initiative')}" if style.get("initiative") else "",
                ) if item
            ],
        ),
        provenance=PersonaProvenanceV1(origin=origin, base_genome_id=base_genome_id),
    )


def persona_genome_to_json(genome: PersonaGenomeV1) -> dict[str, Any]:
    return genome.model_dump(mode="json", exclude_none=True)


def canonical_persona_genome_json(genome: PersonaGenomeV1 | dict[str, Any]) -> str:
    model = genome if isinstance(genome, PersonaGenomeV1) else PersonaGenomeV1.model_validate(genome)
    return json.dumps(persona_genome_to_json(model), sort_keys=True, separators=(",", ":"))


def persona_genome_hash(genome: PersonaGenomeV1 | dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_persona_genome_json(genome).encode("utf-8")).hexdigest()
    return f"pgv1_{digest[:32]}"


def prompt_hash(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return f"prompt_{digest[:32]}"


def _float01(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, parsed))


__all__ = [
    "PERSONA_COMPILER_VERSION",
    "PERSONA_GENOME_SCHEMA_VERSION",
    "PersonaEvidenceRef",
    "PersonaEvolutionPatch",
    "PersonaEvolutionPolicyV1",
    "PersonaEvolutionProposalEvent",
    "PersonaGenomeV1",
    "PersonaIdentityCore",
    "PersonaMemoryAdapterV1",
    "PersonaObservationEvent",
    "PersonaProvenanceV1",
    "PersonaRelationship",
    "PersonaStyleCompilerV1",
    "PersonaTraitState",
    "ResolvedRuntimeIdentity",
    "build_default_persona_genome",
    "canonical_persona_genome_json",
    "normalize_persona_genome",
    "persona_genome_hash",
    "persona_genome_to_json",
    "prompt_hash",
]
