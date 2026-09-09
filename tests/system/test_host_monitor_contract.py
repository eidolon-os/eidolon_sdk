import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from eidolon_sdk.system.v1.host_monitor import (
    HostMonitorWire,
    MonitorCore,
    MonitorMemory,
    MonitorProcessor,
)


def test_monitor_schema_matches_shared_binding():
    path = Path(__file__).resolve().parents[2] / "contracts/system/v1/host-monitor.schema.json"
    schema = json.loads(path.read_text())
    expected = HostMonitorWire.model_json_schema()
    assert {k: v for k, v in schema.items() if k not in ("$schema", "$id")} == expected
    data = HostMonitorWire(
        observed_at=datetime.now(UTC),
        hostname="host",
        cpu=MonitorProcessor(device_id="cpu"),
        memory=MonitorMemory(),
    )
    Draft202012Validator(schema).validate(data.model_dump(mode="json"))


@pytest.mark.parametrize("value", [-1, 101, float("nan"), float("inf")])
def test_invalid_usage_is_rejected(value):
    with pytest.raises(ValidationError):
        MonitorCore(core_id="0", usage_percent=value)
