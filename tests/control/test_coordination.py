import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.control.coordination import CoordinationSelection
from eidolon_sdk.device_foundation.v1.testing import named_device_instance_id


def selection():
    def ref(name):
        return dict(
            device_instance_id=named_device_instance_id(name),
            owner_domain_id="owner-domain-1",
            owner_domain_generation=1,
            claim_generation=1,
            trust_epoch=1,
        )

    return dict(
        scenario="ip_role_group",
        session_id="scene-1",
        input_device=ref("input"),
        members=[
            dict(companion_id="companion-a", output_device=ref("output-a")),
            dict(companion_id="companion-b", output_device=ref("output-b")),
        ],
    )


def test_selection_round_trips_with_one_input_and_separate_members():
    scene = CoordinationSelection.model_validate(selection())
    assert CoordinationSelection.model_validate_json(scene.model_dump_json()) == scene
    assert len(scene.devices) == 3
    assert scene.input_mode == "ptt"
    assert scene.goal == ""
    assert [m.companion_id for m in scene.members] == ["companion-a", "companion-b"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("scenario", "solo"),
        ("scenario", "directed"),
        ("schema_version", True),
        ("schema_version", "1"),
        ("schema_version", 1.0),
        ("schema_version", 1),
        ("input_mode", "full_duplex"),
        ("discussion", "false"),
        ("discussion", 1),
        ("reply_budget", True),
        ("reply_budget", 0),
        ("reply_budget", 33),
        ("owner_id", "forged"),
        ("room", "forged"),
        ("runtime_token", "forged"),
        ("session_id", ""),
        ("session_id", "bad id"),
    ],
)
def test_rejects_ambiguous_policy_and_caller_supplied_authority(field, value):
    payload = selection()
    payload[field] = value
    with pytest.raises(ValidationError):
        CoordinationSelection.model_validate(payload)


@pytest.mark.parametrize(
    "case", ["input", "output", "companion", "domain", "epoch", "empty", "many"]
)
def test_rejects_invalid_membership(case):
    payload = selection()
    a, b = payload["members"]
    if case == "input":
        a["output_device"] = payload["input_device"]
    if case == "output":
        b["output_device"] = a["output_device"]
    if case == "companion":
        b["companion_id"] = a["companion_id"]
    if case == "domain":
        b["output_device"]["owner_domain_id"] = "owner-domain-2"
    if case == "epoch":
        b["output_device"]["owner_domain_generation"] = 2
    if case == "empty":
        payload["members"] = []
    if case == "many":
        payload["members"] *= 9
    with pytest.raises(ValidationError):
        CoordinationSelection.model_validate(payload)


def test_single_response_device_and_explicit_bounded_discussion_are_supported():
    payload = selection()
    payload.update(members=payload["members"][:1], goal="讨论旅行", reply_budget=4)
    scene = CoordinationSelection.model_validate(payload)
    assert len(scene.devices) == 2
    assert scene.goal == "讨论旅行" and scene.reply_budget == 4


def test_group_scenario_must_be_explicit_even_with_one_member():
    payload = selection()
    payload.pop("scenario")
    payload["members"] = payload["members"][:1]
    with pytest.raises(ValidationError):
        CoordinationSelection.model_validate(payload)


def test_scene_roles_round_trip_without_changing_member_binding():
    payload = selection()
    payload['members'][0]['role'] = dict(name=' 孙悟空 ', description='机敏果敢')
    scene = CoordinationSelection.model_validate(payload)
    assert scene.members[0].role.name == '孙悟空'
    assert scene.members[0].companion_id == 'companion-a'
    assert scene.members[1].role is None
    assert CoordinationSelection.model_validate_json(scene.model_dump_json()) == scene


@pytest.mark.parametrize('value', [True, '1', 1.0, 2])
def test_scene_assignments_are_immutable_version_one(value):
    with pytest.raises(ValidationError):
        CoordinationSelection.model_validate(selection() | {'assignment_revision': value})


@pytest.mark.parametrize('role', [dict(name=' '), dict(name='x'*81),
                                dict(name='悟空', description='x'*1001),
                                dict(name='悟空', companion_id='forged')])
def test_role_data_is_bounded_and_cannot_supply_authority(role):
    payload = selection()
    payload['members'][0]['role'] = role
    with pytest.raises(ValidationError):
        CoordinationSelection.model_validate(payload)
