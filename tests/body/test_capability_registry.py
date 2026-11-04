import pytest

from eidolon_sdk.biz.capabilities import (
    CapabilityDefinition,
    CapabilityRegistry,
    installed_registry,
    validate,
)


def extension(**changes):
    return CapabilityDefinition(
        name="example.blink",
        llm_name="example_blink",
        description="Blink the installed light.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        required_output="motion",
        execution_location="device",
        **changes,
    )


def test_extension_projects_without_changing_generic_names():
    registry = CapabilityRegistry()
    registry.register(extension())
    snapshot = registry.snapshot(["example.blink"], conversation_id="session", policy_revision=3)
    assert registry.accept(
        ["example.blink"], snapshot, conversation_id="session", outputs={"motion": True}
    ) == {"example.blink"}
    assert not registry.accept(
        ["example.blink"], snapshot, conversation_id="session", outputs={"motion": False}
    )
    with pytest.raises(ValueError):
        registry.accept(
            ["example.blink"], snapshot, conversation_id="other", outputs={"motion": True}
        )
    snapshot["contracts"][0]["digest"] = "0" * 64
    with pytest.raises(ValueError):
        registry.accept(
            ["example.blink"], snapshot, conversation_id="session", outputs={"motion": True}
        )


def test_conflict_and_mutation_are_isolated():
    registry = CapabilityRegistry()
    d = extension()
    registry.register(d)
    d.input_schema["type"] = "string"
    assert registry.get(d.name).input_schema["type"] == "object"
    with pytest.raises(ValueError):
        registry.register(extension(version=2))
    with pytest.raises(ValueError):
        registry.register(extension().model_copy(update={"name": "other.blink"}))


def test_music_alternatives_and_no_unknown_keywords():
    schema = installed_registry().get("music.search").input_schema
    validate(schema, {"title": "song"})
    with pytest.raises(ValueError):
        validate(schema, {})
    with pytest.raises(ValueError):
        validate(schema, {"title": False})
    with pytest.raises(ValueError):
        CapabilityDefinition(
            **{
                **extension().model_dump(),
                "input_schema": {"type": "object", "$ref": "https://example.invalid"},
            }
        )


def test_legacy_only_opted_in_definitions():
    assert installed_registry().accept(
        ["music.play", "motion.shake", "unknown.action"], None, conversation_id="s", outputs={}
    ) == {"music.play"}


def test_protobuf_integer_recovery_is_schema_scoped():
    from eidolon_sdk.biz.capabilities import decode_arguments

    schema = installed_registry().get("motion.shake").input_schema
    assert decode_arguments(schema, {"repeats": 2.0}) == {"repeats": 2}
    assert type(decode_arguments(schema, {"repeats": 2.0})["repeats"]) is int
    for bad in [1.5, float("inf"), float(2**53)]:
        with pytest.raises(ValueError):
            decode_arguments(schema, {"repeats": bad})
    with pytest.raises(ValueError):
        validate(schema, decode_arguments(schema, {"repeats": True}))
