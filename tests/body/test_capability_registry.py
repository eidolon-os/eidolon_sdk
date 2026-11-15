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


def test_response_attachment_is_explicit_and_requires_background():
    with pytest.raises(ValueError, match="requires background"):
        extension(supports_response_attachment=True)
    definition = extension(supports_background=True, supports_response_attachment=True)
    assert definition.supports_response_attachment
    assert not installed_registry().get("music.play").supports_response_attachment


def test_unmodified_packages_keep_their_previous_digest():
    from eidolon_sdk.biz.capabilities import digest
    definition = extension()
    previous = definition.model_dump(mode="json")
    for added_later in (
        "supports_response_attachment", "required_input", "model_tool", "owner_control"
    ):
        previous.pop(added_later)
    assert definition.contract_digest == digest(previous)


def test_a_capability_is_gated_by_one_output_or_one_input():
    with pytest.raises(ValueError, match="one output or one input"):
        extension(required_input="camera")
    with pytest.raises(ValueError, match="one output or one input"):
        CapabilityDefinition(
            **extension().model_dump(exclude={"required_output"}), required_output=None
        )
    still = installed_registry().get("camera.capture")
    assert (still.required_output, still.required_input) == (None, "camera")
    assert still.execution_location == "device" and not still.model_tool
    assert still.action()["name"] == "camera.capture"


def test_an_input_gated_capability_needs_the_owner_to_allow_capture():
    registry = installed_registry()
    names = ["camera.capture", "motion.nod"]
    snapshot = registry.snapshot(names, conversation_id="session", policy_revision=3)

    def accepted(**selection):
        return registry.accept(names, snapshot, conversation_id="session", **selection)

    assert accepted(outputs={"motion": True}) == {"motion.nod"}
    assert accepted(outputs={"motion": True}, inputs={"camera": "local"}) == {"motion.nod"}
    assert accepted(outputs={}, inputs={"camera": "capture"}) == {"camera.capture"}
    assert accepted(outputs={"motion": True}, inputs={"camera": "capture"}) == set(names)


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


def test_who_is_in_view_is_a_camera_gated_channel_tool_and_leaves_other_digests_alone():
    registry = installed_registry()
    who = registry.get("vision.who")
    assert (who.execution_location, who.required_input, who.model_tool) == ("channel", "camera", True)
    assert not who.side_effect and who.input_schema["properties"] == {}
    names = ["camera.capture", "vision.who"]
    snapshot = registry.snapshot(names, conversation_id="s", policy_revision=3)
    accept = lambda inputs: registry.accept(  # noqa: E731
        names, snapshot, conversation_id="s", outputs={}, inputs=inputs
    )
    assert accept({"camera": "capture"}) == frozenset(names)
    assert accept({"camera": "local"}) == frozenset()
    # A device's own set never lists it, so the revision devices compute is unchanged.
    device_only = registry.snapshot(["camera.capture"], conversation_id="s", policy_revision=3)
    assert all(c["name"] != "vision.who" for c in device_only["contracts"])


def test_who_result_carries_names_and_never_scores():
    from eidolon_sdk.biz.capabilities import validate

    schema = installed_registry().get("vision.who").result_schema
    good = {
        "faces": 1,
        "enrolled": 2,
        "visible": [{"status": "identified", "name": "Ada"}],
        "voice": {"status": "unidentified"},
        "agreement": "face_only",
        "address_as": "Ada",
        "summary": "s",
    }
    validate(schema, good)
    for extra in ({"score": 0.9}, {"person_id": "x"}):
        with pytest.raises(ValueError):
            validate(schema, good | {"visible": [{"status": "identified", "name": "Ada"} | extra]})
    with pytest.raises(ValueError):
        validate(schema, good | {"vector": [0.1]})
