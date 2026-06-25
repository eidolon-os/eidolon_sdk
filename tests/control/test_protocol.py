from __future__ import annotations

from datetime import UTC, datetime

from eidolon_sdk.biz.contracts import CONTROL_TOPIC
from eidolon_sdk.biz.control import (
    build_command_envelope,
    command_status_from_ack,
    infer_op,
    normalize_ack_status,
)


def test_build_command_envelope_pins_wire_shape() -> None:
    envelope = build_command_envelope(
        command_id="cmd-1",
        device_id="esp32-1",
        payload={"reason": "test"},
        op="config.refresh",
        ttl_ms=1000,
        priority="high",
        created_at=datetime(2026, 6, 16, tzinfo=UTC),
    )

    assert CONTROL_TOPIC == "eidolon.control"
    assert envelope == {
        "v": 1,
        "kind": "cmd",
        "id": "cmd-1",
        "op": "config.refresh",
        "ts": 1781568000000,
        "ttl_ms": 1000,
        "qos": "ack",
        "priority": "high",
        "src": {"type": "hub", "id": "eidolon_hub"},
        "dst": {"type": "device", "id": "esp32-1"},
        "payload": {"reason": "test"},
        "caps": ["ack.v1", "result.v1"],
        "type": "config.refresh",
        "command_id": "cmd-1",
        "device_id": "esp32-1",
    }


def test_infer_op_and_ack_status_normalization() -> None:
    assert infer_op({"type": "config.refresh"}) == "config.refresh"
    assert infer_op({"command": "reboot"}) == "reboot"
    assert infer_op({}, explicit_op="screen.set") == "screen.set"
    assert infer_op({}) == "device.command"

    assert normalize_ack_status("ACCEPTED") == "accepted"
    assert normalize_ack_status("unknown") == "failed"
    assert command_status_from_ack("unsupported") == "failed"
    assert command_status_from_ack("running") == "running"
