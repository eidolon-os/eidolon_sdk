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
    "直接回应 owner 当前的意图，说够就停；不默认补建议或追问。",
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
    auto_apply_low_risk: bool = False
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


class PersonaAuthoring(BaseModel):
    """What a person can decide about an Eidolon before it has been anything.

    Split from :class:`PersonaAuthoringDraft` so the name is the only difference
    between them. That split is what lets this be a *wire* shape: when someone
    asks for another Eidolon they already said what to call it, and a request
    carrying the name twice is a request that can disagree with itself.

    Every field has the value the template would have used, so this doubles as
    the starting point a screen shows. A person opening the form sees what their
    Eidolon would be if they typed nothing, and edits from there — which is a
    different act from filling in blanks and imagining the result.

    Deliberately open. These are sentences and lists a person writes, not
    validated policy; the canonical genome is what gets validated, and it is
    built from this by :func:`build_persona_genome_from_draft` rather than
    stored as typed.
    """

    model_config = ConfigDict(extra="forbid")

    archetype: str = "companion"
    self_concept: str = ""
    character_portrait: str = "一个沉稳、专注、愿意长期理解 owner 的伙伴。"
    relationship_narrative: str = ""
    voice_portrait: str = "温暖、清晰、具体，不用空泛语言填补回应。"
    values: list[str] = Field(default_factory=lambda: list(DEFAULT_PERSONA_VALUES))
    boundaries: list[str] = Field(default_factory=lambda: list(DEFAULT_PERSONA_BOUNDARIES))
    safety_boundaries: list[str] = Field(default_factory=list)
    behavior_guidance: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PERSONA_BEHAVIOR_GUIDANCE)
    )
    dialogue_examples: list[str] = Field(default_factory=list)
    modality_notes: dict[str, str] = Field(default_factory=dict)
    traits: dict[str, PersonaTraitState] = Field(default_factory=dict)


class ConversationPreferences(BaseModel):
    """Explicit owner choices, stored outside the immutable genome."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    response_length: Literal["brief", "balanced", "detailed"] = "brief"
    advice: Literal["when_asked", "proactive"] = "when_asked"
    follow_up: Literal["when_needed", "conversational"] = "when_needed"


class PersonaEditSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    genome_id: str
    display_name: str = ""
    companion_revision: int = 1
    persona: PersonaAuthoring
    preferences: ConversationPreferences = Field(default_factory=ConversationPreferences)
    preference_revision: int = Field(default=1, ge=1)


class PersonaEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_base_genome_id: str = Field(min_length=1, max_length=64)
    expected_preference_revision: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=128)
    persona: PersonaAuthoring
    preferences: ConversationPreferences | None = None
    action: Literal["edit", "rename", "restore"] = "edit"
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    restore_genome_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _check_action(self):
        if self.action == "rename":
            if not self.display_name or not self.display_name.strip() or self.restore_genome_id:
                raise ValueError("rename requires a nonblank display_name only")
        elif self.action == "restore":
            if not self.restore_genome_id or self.display_name:
                raise ValueError("restore requires restore_genome_id only")
        elif self.display_name is not None or self.restore_genome_id is not None:
            raise ValueError("edit cannot rename or restore")
        if self.action != "edit" and (
            self.persona.model_fields_set or self.preferences is not None
        ):
            raise ValueError("rename and restore cannot also edit persona or preferences")
        return self


def apply_persona_authoring(
    base: PersonaGenome, authored: PersonaAuthoring, *, base_genome_id: str
) -> PersonaGenome:
    """Apply explicitly supplied authored fields to the full snapshot.

    Omission preserves a value; an empty list/string clears it. Runtime and
    evolution state never round-trips through a form. Validate the full result.
    """
    payload = base.model_dump(mode="json")
    paths = {
        "archetype": ("constitution", "archetype"),
        "self_concept": ("constitution", "self_concept"),
        "values": ("constitution", "values"),
        "boundaries": ("constitution", "boundaries"),
        "character_portrait": ("character", "portrait"),
        "traits": ("character", "traits"),
        "relationship_narrative": ("relationship", "narrative"),
        "safety_boundaries": ("relationship", "safety_boundaries"),
        "voice_portrait": ("expression", "voice_portrait"),
        "behavior_guidance": ("expression", "behavior_guidance"),
        "dialogue_examples": ("expression", "dialogue_examples"),
        "modality_notes": ("expression", "modality_notes"),
    }
    for field, value in authored.model_dump(mode="json", exclude_unset=True).items():
        section, key = paths[field]
        payload[section][key] = value.strip() if isinstance(value, str) else value
    payload["provenance"].update(origin="owner_authored", base_genome_id=base_genome_id)
    return PersonaGenome.model_validate(payload)


class PersonaAuthoringDraft(PersonaAuthoring):
    """One person's authoring, for one named Eidolon.

    The name is required here and absent from the base on purpose: a genome
    without an identity is not a genome (see ``PersonaGenome``), while a form
    someone is still filling in has no business restating a name the request
    already carries.
    """

    name: str

    @model_validator(mode="after")
    def _ensure_name(self) -> "PersonaAuthoringDraft":
        if not self.name.strip():
            raise ValueError("persona authoring draft name is required")
        return self

    @classmethod
    def for_companion(
        cls, authoring: PersonaAuthoring | None, *, name: str
    ) -> "PersonaAuthoringDraft":
        """The draft for a Companion called ``name``, authored or not.

        ``None`` means nobody authored anything, and the answer is the template
        under this name — the same genome the create path has always written
        when asked for nothing. So a caller does not branch on whether a person
        filled in the form; it asks for the draft either way.
        """

        fields = {} if authoring is None else authoring.model_dump()
        return cls(**fields, name=name)


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
            auto_apply_low_risk=False,
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


def persona_authoring_of(genome: PersonaGenome) -> PersonaAuthoring:
    """Read a committed genome back as the part a person wrote.

    The inverse of :func:`build_persona_genome_from_draft`, and it exists for one
    screen: editing who an Eidolon is has to open on **who it currently is**, not
    on the template and not on blanks. A form that opened on anything else would
    make every edit a rewrite, because whatever the person did not retype would
    be lost the moment they saved.

    Only the authored fields come back. A genome also carries things nobody
    typed — hashes, schema and realizer versions, provenance, evolution policy —
    and those are how a Companion is *built*, not what somebody decided about
    it. Round-tripping them through a form would let a screen edit machinery it
    has no business touching.

    Apply edits with apply_persona_authoring against the full stored snapshot;
    build_persona_genome_from_draft is for creation only.
    """

    return PersonaAuthoring(
        archetype=genome.constitution.archetype,
        self_concept=genome.constitution.self_concept,
        values=list(genome.constitution.values),
        boundaries=list(genome.constitution.boundaries),
        character_portrait=genome.character.portrait,
        traits=dict(genome.character.traits),
        relationship_narrative=genome.relationship.narrative,
        safety_boundaries=list(genome.relationship.safety_boundaries),
        voice_portrait=genome.expression.voice_portrait,
        behavior_guidance=list(genome.expression.behavior_guidance),
        dialogue_examples=list(genome.expression.dialogue_examples),
        modality_notes=dict(genome.expression.modality_notes),
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
    "operation_conflict",
    "preferences_changed",
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
    "PersonaPreviewRequest",
    "PersonaPreviewResponse",
    "PersonaPreset",
    "PersonaPresetCatalog",
    "persona_preset_catalog",
    "validate_persona_evolution",
    "ConversationPreferences",
    "PersonaEditSnapshot",
    "PersonaEditRequest",
    "apply_persona_authoring",
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


class PersonaPreset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    preset_id: str
    revision: str = "1"
    title: str
    persona: PersonaAuthoring
    examples: list[str]


class PersonaPresetCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    presets: list[PersonaPreset]


def persona_preset_catalog() -> PersonaPresetCatalog:
    """Data publishes these authoring snapshots; clients do not invent defaults."""
    default = PersonaAuthoring()
    definitions = [
        (
            "gentle",
            "温和陪伴",
            default,
            [
                "你：你好。\nTA：嗨，很高兴见到你。",
                "你：今天有点累。\nTA：辛苦了，先歇一会儿。我在。",
                "你：帮我做个选择。\nTA：你在考虑哪两个选项？",
            ],
        ),
        (
            "direct",
            "直接务实",
            default.model_copy(
                update={
                    "character_portrait": "直接、踏实，尊重 owner 自己的判断。",
                    "voice_portrait": "用具体的短句回答；需要解释时清楚展开。",
                }
            ),
            [
                "你：你好。\nTA：你好，我在。",
                "你：今天有点累。\nTA：听起来今天消耗很大。先缓一缓。",
                "你：帮我做个选择。\nTA：有哪些选项，你最看重什么？",
            ],
        ),
        (
            "playful",
            "活泼有趣",
            default.model_copy(
                update={
                    "character_portrait": "活泼、好奇，有轻盈的幽默感，也能安静听人说话。",
                    "voice_portrait": "自然轻快，偶尔幽默；不把每句话都变成表演。",
                }
            ),
            [
                "你：你好。\nTA：嗨，我来啦。",
                "你：今天有点累。\nTA：今天的电量见底了吧。我陪你缓一缓。",
                "你：帮我做个选择。\nTA：把候选选手告诉我，我们一起看看。",
            ],
        ),
    ]
    return PersonaPresetCatalog(
        presets=[
            PersonaPreset(preset_id=key, title=title, persona=persona, examples=examples)
            for key, title, persona, examples in definitions
        ]
    )


def validate_persona_evolution(
    current: PersonaGenome, proposal: PersonaEvolutionProposalEvent
) -> None:
    """Shared validation, enforced again by Data before recording/approving proposals.

    Explicit owner settings are edited through authoring, never inferred from memory.
    All accepted proposals still require the existing explicit approval command.
    """
    candidate = proposal.proposed_genome
    if not current.evolution_policy.enabled:
        raise ValueError("persona evolution is disabled")
    if not proposal.rationale.strip() or not proposal.evidence_refs:
        raise ValueError("persona evolution requires rationale and evidence")
    if candidate.constitution != current.constitution:
        raise ValueError("memory-driven evolution cannot rewrite the constitution")
    for field in ("memory_policy", "evolution_policy"):
        if getattr(candidate, field) != getattr(current, field):
            raise ValueError(f"memory-driven evolution cannot rewrite {field}")
    before_relation = current.relationship.model_dump(exclude={"stage"})
    after_relation = candidate.relationship.model_dump(exclude={"stage"})
    if before_relation != after_relation:
        raise ValueError("memory-driven evolution cannot rewrite relationship agreements")
    if candidate.character.traits.keys() != current.character.traits.keys():
        raise ValueError("persona evolution cannot add or remove traits")
    for key, before in current.character.traits.items():
        if (
            abs(candidate.character.traits[key].value - before.value)
            > current.evolution_policy.max_delta_per_commit
        ):
            raise ValueError(f"persona trait delta exceeds max_delta_per_commit: {key}")
    stages = ("new", "familiar", "trusted", "deep")
    delta = stages.index(candidate.relationship.stage) - stages.index(current.relationship.stage)
    if delta < 0 or delta > 1:
        raise ValueError("relationship stage evolution must move forward one step at most")


class PersonaPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    companion_id: str | None = None
    base_genome_id: str | None = None
    name: str = Field(min_length=1, max_length=128)
    persona: PersonaAuthoring
    preferences: ConversationPreferences = Field(default_factory=ConversationPreferences)
    text: str = Field(min_length=1, max_length=2000)
    modality: Literal["voice", "text"] = "voice"

    @model_validator(mode="after")
    def _valid_draft(self):
        if bool(self.companion_id) != bool(self.base_genome_id):
            raise ValueError("companion_id and base_genome_id must be supplied together")
        if not self.name.strip() or not self.text.strip():
            raise ValueError("preview name and text cannot be blank")
        return self


class PersonaPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_digest: str
    reply: str
    finish_reason: str
    truncated: bool = False
