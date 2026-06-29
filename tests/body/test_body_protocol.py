from __future__ import annotations

from eidolon_sdk.biz.body import (
    BODY_OP_DEVICE_IDENTIFY,
    BODY_OP_SOUND_PLAY,
    BodyCommandResult,
    capabilities_from_json,
    command_result_to_dict,
)


def test_capabilities_from_json_accepts_ops_list() -> None:
    capabilities = capabilities_from_json({"ops": ["sound.play", "display.update"]})

    assert [item.name for item in capabilities] == ["sound.play", "display.update"]
    assert capabilities[0].input_schema["required"] == ["sound"]


def test_capabilities_from_json_defaults_known_esp32_body_ops() -> None:
    capabilities = capabilities_from_json({}, device_kind="esp-box-3")

    names = {item.name for item in capabilities}
    assert BODY_OP_SOUND_PLAY in names
    assert BODY_OP_DEVICE_IDENTIFY in names
    assert "room.join" in names


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
