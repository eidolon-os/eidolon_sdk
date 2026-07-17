from __future__ import annotations

from eidolon_sdk.biz.body import (
    BODY_OP_PRESENCE_SET,
    BodyCommandResult,
    capabilities_from_json,
    command_result_to_dict,
)


def test_capabilities_from_json_accepts_ops_list() -> None:
    capabilities = capabilities_from_json({"ops": ["sound.play", "display.update"]})

    assert [item.name for item in capabilities] == ["sound.play", "display.update"]
    assert capabilities[0].input_schema["required"] == ["sound"]


def test_capabilities_from_json_does_not_guess_ops_from_device_kind() -> None:
    capabilities = capabilities_from_json({}, device_kind="esp-box-3")
    assert capabilities == ()


def test_capabilities_from_json_can_filter_unknown_ops() -> None:
    capabilities = capabilities_from_json(
        {"ops": ["device.roll_call", "vendor.unreviewed"]},
        known_only=True,
    )
    assert [item.name for item in capabilities] == ["device.roll_call"]


def test_presence_set_is_explicit_body_capability() -> None:
    capabilities = capabilities_from_json({"ops": [BODY_OP_PRESENCE_SET]})

    assert len(capabilities) == 1
    capability = capabilities[0]
    assert capability.name == BODY_OP_PRESENCE_SET
    assert capability.risk_level == "low"
    assert capability.input_schema["required"] == [
        "state",
        "guard_epoch",
        "correlation_id",
        "action_id",
    ]


def test_command_result_ok_is_status_based() -> None:
    sent = BodyCommandResult(command_id="c1", device_id="d1", op="sound.play", status="sent")
    failed = BodyCommandResult(
        command_id="c2",
        device_id="d1",
        op="sound.play",
        status="offline",
        error="offline",
    )

    assert command_result_to_dict(sent)["ok"] is True
    assert command_result_to_dict(failed)["ok"] is False
