import json
from types import SimpleNamespace

import pytest

from eidolon_sdk.biz.capabilities import (
    declared_observable_properties,
    installed_properties,
    installed_registry,
    validate,
)
from eidolon_sdk.biz.capabilities.device_settings import (
    AUDIO_VOLUME,
    AUDIO_VOLUME_ADJUST,
    AUDIO_VOLUME_SET,
    DISPLAY_BRIGHTNESS,
    DISPLAY_BRIGHTNESS_ADJUST,
    DISPLAY_BRIGHTNESS_SET,
)
from eidolon_sdk.biz.contracts import EVENT_TOPIC
from eidolon_sdk.biz.presentation.capability_rpc import ExecutionScope, standing_scope
from eidolon_sdk.biz.presentation.device_properties import (
    PROPERTY_CHANGED,
    PropertyValues,
    read_property_change,
    read_property_values,
)

SETTERS = (AUDIO_VOLUME_SET, DISPLAY_BRIGHTNESS_SET)
ADJUSTERS = (AUDIO_VOLUME_ADJUST, DISPLAY_BRIGHTNESS_ADJUST)


def test_settings_are_device_capabilities_gated_on_the_output_they_tune():
    registry = installed_registry()
    for name in (*SETTERS, *ADJUSTERS):
        definition = registry.get(name)
        assert definition.execution_location == "device"
        assert definition.body_control and definition.idempotent and definition.model_tool
        assert definition.completion_basis == "configuration_applied"
    assert registry.get(AUDIO_VOLUME_SET).required_output == "speech"
    assert registry.get(AUDIO_VOLUME_ADJUST).required_output == "speech"
    assert registry.get(DISPLAY_BRIGHTNESS_SET).required_output == "expression"
    assert registry.get(DISPLAY_BRIGHTNESS_ADJUST).required_output == "expression"


def test_only_the_setters_are_offered_to_the_owners_app():
    registry = installed_registry()
    assert [n for n in (*SETTERS, *ADJUSTERS) if registry.get(n).owner_control] == list(SETTERS)
    # Nothing that existed before this field opted into it.
    assert not any(
        d.owner_control for d in registry.definitions() if d.name not in SETTERS
    )


def test_permitted_follows_the_selected_outputs():
    registry = installed_registry()
    names = [*SETTERS, *ADJUSTERS, "camera.capture"]
    assert registry.permitted(names, outputs={"speech": True}) == {
        AUDIO_VOLUME_SET, AUDIO_VOLUME_ADJUST,
    }
    assert registry.permitted(names, outputs={"expression": True}) == {
        DISPLAY_BRIGHTNESS_SET, DISPLAY_BRIGHTNESS_ADJUST,
    }
    assert registry.permitted(
        names, outputs={"speech": True}, inputs={"camera": "capture"}
    ) == {AUDIO_VOLUME_SET, AUDIO_VOLUME_ADJUST, "camera.capture"}
    assert registry.permitted(["not.installed"], outputs={"speech": True}) == frozenset()


def test_setter_and_adjuster_arguments_are_bounded():
    registry = installed_registry()
    validate(registry.get(AUDIO_VOLUME_SET).input_schema, {"volume": 0})
    validate(registry.get(AUDIO_VOLUME_SET).input_schema, {"volume": 100})
    validate(registry.get(AUDIO_VOLUME_ADJUST).input_schema, {"change": -100})
    for bad in ({"volume": 101}, {"volume": -1}, {"volume": 1.5}, {}, {"volume": 5, "x": 1}):
        with pytest.raises(ValueError):
            validate(registry.get(AUDIO_VOLUME_SET).input_schema, bad)
    with pytest.raises(ValueError):
        validate(registry.get(DISPLAY_BRIGHTNESS_ADJUST).input_schema, {"change": 101})
    # Both forms answer with the value the device applied.
    validate(registry.get(AUDIO_VOLUME_ADJUST).result_schema, {"volume": 42})
    validate(registry.get(DISPLAY_BRIGHTNESS_ADJUST).result_schema, {"brightness": 42})


def test_the_manifest_action_a_device_must_declare_is_the_registered_one():
    action = installed_registry().get(AUDIO_VOLUME_SET).action()
    assert action == {
        "name": "audio.volume.set",
        "version": 1,
        "input_schema": {
            "type": "object",
            "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["volume"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["volume"],
            "additionalProperties": False,
        },
        "idempotent": True,
    }


def test_observable_properties_are_the_installed_declarations_and_nothing_wider():
    installed = installed_properties()
    assert set(installed) == {AUDIO_VOLUME, DISPLAY_BRIGHTNESS}
    manifest = {
        "properties": [
            installed[AUDIO_VOLUME],
            # Same name, wider schema: the device cannot widen what the Host checks.
            {**installed[DISPLAY_BRIGHTNESS], "schema": {"type": "integer"}},
            {"name": "battery.level", "schema": {"type": "integer"}, "observable": True,
             "writable": False},
        ]
    }
    assert declared_observable_properties(manifest) == {
        AUDIO_VOLUME: {"type": "integer", "minimum": 0, "maximum": 100}
    }
    assert declared_observable_properties({}) == {}
    # A caller mutating the answer does not change the installed set.
    installed[AUDIO_VOLUME]["schema"]["maximum"] = 1
    assert installed_properties()[AUDIO_VOLUME]["schema"]["maximum"] == 100


def _event(**changes):
    body = {
        "schema_v": 1,
        "kind": "event",
        "event_id": "evt-1",
        "flow_id": "flow-1",
        "causation_id": "",
        "type": PROPERTY_CHANGED,
        "source": {"device_id": "dev-1", "component": "settings"},
        "occurred_at_ms": 1_800_000_000_000,
        "expires_at_ms": 1_800_000_002_000,
        "payload": {"name": AUDIO_VOLUME, "value": 35},
    }
    body.update(changes)
    return body


def _packet(body, *, sender="dev-1", topic=EVENT_TOPIC):
    return SimpleNamespace(
        topic=topic,
        participant=SimpleNamespace(identity=sender),
        data=json.dumps(body).encode() if not isinstance(body, bytes) else body,
    )


DECLARED = {AUDIO_VOLUME: {"type": "integer", "minimum": 0, "maximum": 100}}


def test_a_declared_property_change_is_read():
    change = read_property_change(_packet(_event()), device="dev-1", declared=DECLARED)
    assert change is not None
    assert (change.device_id, change.name, change.value, change.event_id) == (
        "dev-1", AUDIO_VOLUME, 35, "evt-1",
    )


@pytest.mark.parametrize(
    "packet",
    [
        _packet(_event(), sender="someone-else"),
        _packet(_event(), topic="eidolon.control"),
        _packet(_event(type="body.state.changed")),
        _packet(_event(schema_v=2)),
        _packet(_event(source={"device_id": "dev-2", "component": "settings"})),
        _packet(_event(payload={"name": DISPLAY_BRIGHTNESS, "value": 10})),
        _packet(_event(payload={"name": AUDIO_VOLUME, "value": 101})),
        _packet(_event(payload={"name": AUDIO_VOLUME, "value": "35"})),
        _packet(_event(occurred_at_ms=-1)),
        _packet(b"not json"),
        _packet(b"x" * 4096),
    ],
)
def test_anything_else_is_not_a_change(packet):
    assert read_property_change(packet, device="dev-1", declared=DECLARED) is None


def test_a_read_answer_keeps_only_declared_admissible_values():
    answer = PropertyValues(values={AUDIO_VOLUME: 20, DISPLAY_BRIGHTNESS: 50, "x": 1})
    assert read_property_values(answer, declared=DECLARED) == {AUDIO_VOLUME: 20}
    assert read_property_values(
        PropertyValues(values={AUDIO_VOLUME: 200}), declared=DECLARED
    ) == {}


def test_a_standing_invocation_is_bound_to_the_channel_room_and_policy():
    scope = standing_scope(execution_id="owner:abc", room="eidolon-0123abcd", policy_revision=4)
    assert scope == ExecutionScope(
        execution_id="owner:abc", session_id="eidolon-0123abcd", policy_revision=4
    )
