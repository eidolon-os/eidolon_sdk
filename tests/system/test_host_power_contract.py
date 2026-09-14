import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from eidolon_sdk.system.v1 import HostPowerOffAccepted, HostPowerOffRequest, HostPowerStatusWire


@pytest.mark.parametrize(
    "model,name",
    [
        (HostPowerStatusWire, "host-power"),
        (HostPowerOffRequest, "host-poweroff-request"),
        (HostPowerOffAccepted, "host-poweroff-accepted"),
    ],
)
def test_power_schemas_match_binding(model, name):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2] / f"contracts/system/v1/{name}.schema.json"
        ).read_text()
    )
    assert {
        k: v for k, v in schema.items() if k not in ("$id", "$schema")
    } == model.model_json_schema()


@pytest.mark.parametrize(
    "data",
    [{}, {"request_id": ""}, {"request_id": "a; reboot"}, {"request_id": "a", "command": "reboot"}],
)
def test_request_cannot_select_a_command(data):
    with pytest.raises(ValidationError):
        HostPowerOffRequest.model_validate(data)
