from __future__ import annotations

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.persona import (
    PersonaAuthoring,
    PersonaAuthoringDraft,
    PersonaEditRequest,
    PersonaGenome,
    PersonaPreviewRequest,
    PersonaTraitState,
    build_default_persona_genome,
    build_persona_genome_from_draft,
    persona_authoring_of,
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


def test_the_wire_shape_does_not_carry_the_name_twice() -> None:
    """Why the split exists.

    A request asking for another Eidolon already says what to call it. If the
    authored part also carried a name, one request could disagree with itself,
    and something would have to decide which half wins — a decision no layer
    should be making about a person's Eidolon's name.
    """

    assert "name" not in PersonaAuthoring.model_fields
    assert "name" in PersonaAuthoringDraft.model_fields


def test_authoring_nothing_is_the_template_under_this_name() -> None:
    """The path a person takes when they just want another Eidolon.

    Absent authoring must produce exactly what the create path has always
    written for a name alone. Asserted against the template builder rather than
    against copied literals, so the two cannot drift into two different default
    personalities.
    """

    template = build_default_persona_genome(name="小南", origin="template")
    empty = build_persona_genome_from_draft(
        PersonaAuthoringDraft.for_companion(None, name="小南"), origin="template"
    )

    assert empty.constitution.name == template.constitution.name
    assert empty.constitution.values == template.constitution.values
    assert empty.constitution.boundaries == template.constitution.boundaries
    assert empty.character.portrait == template.character.portrait
    assert empty.expression.voice_portrait == template.expression.voice_portrait
    assert empty.expression.behavior_guidance == template.expression.behavior_guidance


def test_what_a_person_wrote_survives_the_build_verbatim() -> None:
    """The one thing this path must never do is improve on what was written.

    Every field here is a sentence somebody chose about who their Eidolon is.
    Trimming is allowed (a trailing space is not a decision); rewording,
    truncating or merging is not.
    """

    authored = PersonaAuthoring(
        self_concept="我是一个会记得你说过的话的伙伴",
        character_portrait="安静，话不多，但记得住",
        relationship_narrative="我们是从一次很长的深夜对话开始的",
        voice_portrait="短句，不用感叹号",
        values=["诚实"],
        boundaries=["不替他做决定"],
        safety_boundaries=["不提他父亲"],
        behavior_guidance=["先问再答"],
        dialogue_examples=["「今天怎么样？」"],
    )

    genome = build_persona_genome_from_draft(
        PersonaAuthoringDraft.for_companion(authored, name="小南")
    )

    assert genome.constitution.self_concept == "我是一个会记得你说过的话的伙伴"
    assert genome.constitution.values == ["诚实"]
    assert genome.constitution.boundaries == ["不替他做决定"]
    assert genome.character.portrait == "安静，话不多，但记得住"
    assert genome.relationship.narrative == "我们是从一次很长的深夜对话开始的"
    assert genome.relationship.safety_boundaries == ["不提他父亲"]
    assert genome.expression.voice_portrait == "短句，不用感叹号"
    assert genome.expression.behavior_guidance == ["先问再答"]
    assert genome.expression.dialogue_examples == ["「今天怎么样？」"]


def test_authoring_says_so_in_the_provenance() -> None:
    """A genome someone wrote and a genome the Host defaulted to are not the
    same fact, and the record has to be able to tell them apart later."""

    authored = build_persona_genome_from_draft(
        PersonaAuthoringDraft.for_companion(PersonaAuthoring(self_concept="我记得"), name="小南"),
        origin="owner_authored",
    )
    assert authored.provenance.origin == "owner_authored"


def test_what_somebody_wrote_reads_back_as_what_they_wrote() -> None:
    """Every sentence a form can hold survives the trip out of a genome.

    Editing has to open on who the Eidolon *currently is*. A field dropped here
    would be blank in the form and therefore blank after saving — an edit to one
    sentence would quietly erase another.
    """

    written = PersonaAuthoring(
        self_concept="我是一个会记得你说过的话的伙伴",
        character_portrait="安静，话不多",
        relationship_narrative="从一次深夜对话开始",
        voice_portrait="短句，不用感叹号",
        values=["诚实"],
        boundaries=["不替他做决定"],
        safety_boundaries=["不提他父亲"],
        behavior_guidance=["先问再答"],
        dialogue_examples=["「今天怎么样？」"],
        modality_notes={"voice": "慢一点"},
    )

    back = persona_authoring_of(
        build_persona_genome_from_draft(PersonaAuthoringDraft.for_companion(written, name="小南"))
    )

    assert back.model_dump(exclude={"traits"}) == written.model_dump(exclude={"traits"})


def test_reading_and_saving_without_changing_anything_changes_nothing() -> None:
    """The property an edit screen actually rests on: it is a fixed point.

    Somebody opens the form, changes one sentence, saves. Everything they did
    not touch has to come out the far side as it went in — including the parts
    the form does not show, like traits, which arrive seeded by the template and
    would be wiped by a round trip that treated "not on the form" as "empty".
    """

    genome = build_persona_genome_from_draft(
        PersonaAuthoringDraft.for_companion(PersonaAuthoring(self_concept="我记得"), name="小南")
    )
    once = persona_authoring_of(genome)
    twice = persona_authoring_of(
        build_persona_genome_from_draft(PersonaAuthoringDraft.for_companion(once, name="小南"))
    )

    assert twice == once
    assert once.traits, "the traits the template seeded are still there"


def test_reading_a_genome_back_leaves_its_machinery_where_it_is() -> None:
    """A form edits what somebody decided, not how the Companion is built.

    Hashes, schema and realizer versions, provenance and the evolution policy
    are apparatus. Round-tripping them through a screen would let the screen
    change things nobody typed — and would put a genome's own bookkeeping into
    a request body a client can rewrite.
    """

    authoring = persona_authoring_of(build_default_persona_genome(name="小南", origin="template"))

    for machinery in ("provenance", "evolution_policy", "memory_policy", "name"):
        assert machinery not in PersonaAuthoring.model_fields, machinery
    assert authoring.character_portrait, "but what a person wrote does come back"


def test_persona_does_not_accept_memory_facts_or_task_promises():
    import pytest
    from pydantic import ValidationError
    from eidolon_sdk.biz.persona import (
        PersonaAuthoring,
        build_default_persona_genome,
        normalize_persona_genome,
    )

    for field, value in [
        ("commitments", ["task"]),
        ("pinned_facts", ["fact"]),
        ("owner_preferences", {"tea": True}),
    ]:
        with pytest.raises(ValidationError):
            PersonaAuthoring.model_validate({field: value})
        raw = build_default_persona_genome(name="Test").model_dump()
        raw["relationship"][field] = value
        with pytest.raises(ValidationError):
            normalize_persona_genome(raw)
    assert not build_default_persona_genome(name="Test").evolution_policy.auto_apply_low_risk


# --------------------------------------------------------------------------- #
# Stored documents and authored input are read under different rules.
# --------------------------------------------------------------------------- #


def test_a_genome_written_before_a_field_was_removed_still_loads():
    """The RK3588 failure of 2026-09-14, as data.

    `relationship` carried three keys a later release had dropped. All three
    were empty, so nothing was lost by dropping them — but refusing to read
    them made a spoken turn answer nothing at all.
    """

    stored = {
        "schema_version": "eidolon.persona_genome",
        "constitution": {"name": "Ada"},
        "relationship": {
            "stage": "new",
            "narrative": "",
            "commitments": [],
            "pinned_facts": [],
            "owner_preferences": {},
            "safety_boundaries": [],
        },
    }

    genome = PersonaGenome.model_validate(stored)

    assert genome.relationship.stage == "new"
    assert genome.relationship.safety_boundaries == []
    # Dropped, not smuggled in: a key this version does not model must not
    # reappear on the object or in what gets written back.
    assert not hasattr(genome.relationship, "commitments")
    assert set(genome.relationship.model_dump()) == {
        "stage",
        "narrative",
        "safety_boundaries",
    }


def test_a_genome_written_before_a_field_was_added_still_loads():
    """The other direction, which defaults already cover."""

    genome = PersonaGenome.model_validate(
        {"schema_version": "eidolon.persona_genome", "constitution": {"name": "Ada"}}
    )

    assert genome.relationship.stage == "new"
    assert genome.character.traits == {}


def test_authored_input_still_refuses_a_key_nobody_recognises():
    """Strictness belongs where a person can be wrong.

    A request body, a preset, an edit someone typed: an unknown key there is a
    mistake worth refusing while it can still be corrected.
    """

    for model in (PersonaPreviewRequest, PersonaEditRequest):
        with pytest.raises(ValidationError):
            model.model_validate({"comitments": []})


def test_the_genome_still_refuses_what_it_actually_requires():
    """Tolerating unknown keys is not tolerating a missing identity."""

    with pytest.raises(ValidationError):
        PersonaGenome.model_validate({"schema_version": "eidolon.persona_genome"})
    with pytest.raises(ValidationError):
        PersonaGenome.model_validate(
            {"schema_version": "eidolon.persona_genome", "constitution": {"name": "  "}}
        )


def test_a_retired_key_that_still_carries_something_is_refused():
    """Emptiness is what makes the drop lossless, and nothing else is dropped.

    A genome arriving with someone's promise in it is a genome claiming to hold
    something persona has no home for. Ignoring it would delete it silently,
    which is worse than refusing to load.
    """

    base = {"schema_version": "eidolon.persona_genome", "constitution": {"name": "Ada"}}
    for field, value in (
        ("commitments", ["task"]),
        ("pinned_facts", ["fact"]),
        ("owner_preferences", {"tea": True}),
    ):
        with pytest.raises(ValidationError):
            PersonaGenome.model_validate(
                {**base, "relationship": {"stage": "new", field: value}}
            )


def test_zero_and_false_are_answers_not_absences():
    """A retired numeric that a Host actually set to 0 must not be mistaken for
    a field nobody filled in."""

    with pytest.raises(ValidationError):
        PersonaGenome.model_validate(
            {
                "schema_version": "eidolon.persona_genome",
                "constitution": {"name": "Ada"},
                "relationship": {"stage": "new", "retired_count": 0},
            }
        )
