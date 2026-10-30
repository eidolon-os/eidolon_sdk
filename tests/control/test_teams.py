import pytest
from pydantic import ValidationError
from eidolon_sdk.biz.control.teams import TeamConfiguration, TeamRevision
from eidolon_sdk.device_foundation.v1 import DeviceRef
from eidolon_sdk.device_foundation.v1.testing import named_device_instance_id as device


def configuration():
    return dict(
        name="聊天伙伴",
        input_device_id=device("input"),
        members=[
            dict(
                companion_id="companion-a",
                output_device_id=device("output"),
                role=dict(name="八戒", description="热情友好的旅伴"),
            )
        ],
    )


def resources():
    return {
        device(name): DeviceRef(
            device_instance_id=device(name),
            owner_domain_id="owner-domain-1",
            owner_domain_generation=1,
            claim_generation=2,
            trust_epoch=1,
        )
        for name in ("input", "output")
    }


def test_revision_resolves_fresh_refs_without_changing_execution_version():
    saved = TeamRevision(
        team_id="team-a", revision=7, configuration=TeamConfiguration(**configuration())
    )
    restored = TeamRevision.model_validate_json(saved.model_dump_json())
    scene = restored.configuration.resolve(
        session_id="run-a", devices=resources(), attachments={device("output"): "companion-a"}
    )
    assert scene.assignment_revision == 1
    assert scene.input_device.claim_generation == 2
    assert scene.members[0].role.name == "八戒"
    assert saved.revision == 7


@pytest.mark.parametrize("binding", [None, "companion-b"])
def test_rebinding_does_not_replace_member(binding):
    with pytest.raises(ValueError, match="TEAM_BINDING_CHANGED"):
        TeamConfiguration(**configuration()).resolve(
            session_id="run-a", devices=resources(), attachments={device("output"): binding}
        )


@pytest.mark.parametrize("missing", [True, False])
def test_device_must_be_present_and_match_reference(missing):
    refs = resources()
    if missing:
        refs.pop(device("output"))
    else:
        refs[device("output")] = refs[device("input")]
    with pytest.raises(ValueError, match="TEAM_DEVICE_"):
        TeamConfiguration(**configuration()).resolve(
            session_id="run-a", devices=refs, attachments={device("output"): "companion-a"}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"owner_id": "forged"},
        {"reply_budget": True},
        {"name": "  "},
        {"input_device_id": device("output")},
        {"members": configuration()["members"] * 2},
    ],
)
def test_invalid_configuration_is_rejected(change):
    with pytest.raises(ValidationError):
        TeamConfiguration(**(configuration() | change))


def test_multiple_saved_teams_can_reference_same_companion():
    config = TeamConfiguration(**configuration())
    teams = [
        TeamRevision(team_id=name, revision=1, configuration=config)
        for name in ("team-a", "team-b")
    ]
    assert teams[0].configuration == teams[1].configuration
