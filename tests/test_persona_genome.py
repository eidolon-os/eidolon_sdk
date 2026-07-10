from __future__ import annotations

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.persona import (
    PersonaAuthoringDraft,
    PersonaGenome,
    PersonaTraitState,
    build_persona_genome_from_draft,
    persona_genome_hash,
    persona_genome_to_json,
)


def test_authoring_draft_builds_semantic_genome_without_field_coercion() -> None:
    genome = build_persona_genome_from_draft(
        PersonaAuthoringDraft(
            name="Yi",
            character_portrait="Quietly perceptive and willing to disagree with care.",
            relationship_narrative="A trusted long-term partner.",
            voice_portrait="Concise, warm, and specific.",
            behavior_guidance=["Lead with the concrete point."],
        )
    )

    assert genome.schema_version == "eidolon.persona_genome"
    assert genome.character.portrait.startswith("Quietly perceptive")
    assert genome.relationship.narrative == "A trusted long-term partner."
    assert genome.expression.voice_portrait == "Concise, warm, and specific."
    assert genome.constitution.values == [
        "温暖而不空泛",
        "诚实说明不确定性",
        "尊重 owner 的主权和最终选择",
    ]
    assert len(genome.character.traits) == 9
    assert "trait_mappings" not in persona_genome_to_json(genome)


def test_namespaced_traits_are_extensible_but_structure_is_strict() -> None:
    genome = build_persona_genome_from_draft(
        PersonaAuthoringDraft(
            name="Yi",
            traits={"creative.associative_leap": PersonaTraitState(value=0.72)},
        )
    )
    assert genome.character.traits["creative.associative_leap"].value == 0.72

    payload = persona_genome_to_json(genome)
    payload["style_compiler"] = {"trait_mappings": {}}
    with pytest.raises(ValidationError):
        PersonaGenome.model_validate(payload)


def test_genome_hash_is_canonical_and_content_addressed() -> None:
    genome = build_persona_genome_from_draft(PersonaAuthoringDraft(name="Yi"))
    payload = persona_genome_to_json(genome)
    assert persona_genome_hash(genome) == persona_genome_hash(dict(reversed(payload.items())))
    assert persona_genome_hash(genome).startswith("pg_")
