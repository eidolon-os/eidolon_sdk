"""The volume/brightness contracts the Agent projects into LLM tools.

These assert the wire contract only: a device that declares one of these
capabilities accepts a bounded percentage and nothing else. Execution lives in
the device, so the schema is the one place the server can refuse a value before
it leaves the Host.
"""

from __future__ import annotations

import pytest

from eidolon_sdk.biz.body import (
    BODY_OP_DISPLAY_BRIGHTNESS,
    BODY_OP_VOLUME_SET,
    KNOWN_BODY_CAPABILITIES,
    validate_capability_arguments,
)


@pytest.mark.parametrize(
    ("op", "field"),
    [
        (BODY_OP_VOLUME_SET, "volume"),
        (BODY_OP_DISPLAY_BRIGHTNESS, "brightness"),
    ],
)
def test_device_control_capability_accepts_in_range_value(op: str, field: str) -> None:
    schema = KNOWN_BODY_CAPABILITIES[op].input_schema

    assert validate_capability_arguments(schema, {field: 50}) is None


@pytest.mark.parametrize(
    ("op", "field"),
    [
        (BODY_OP_VOLUME_SET, "volume"),
        (BODY_OP_DISPLAY_BRIGHTNESS, "brightness"),
    ],
)
@pytest.mark.parametrize("value", [-1, 101])
def test_device_control_capability_rejects_out_of_range_value(
    op: str, field: str, value: int
) -> None:
    schema = KNOWN_BODY_CAPABILITIES[op].input_schema

    assert validate_capability_arguments(schema, {field: value}) is not None


@pytest.mark.parametrize(
    ("op", "field"),
    [
        (BODY_OP_VOLUME_SET, "volume"),
        (BODY_OP_DISPLAY_BRIGHTNESS, "brightness"),
    ],
)
def test_device_control_capability_requires_its_value(op: str, field: str) -> None:
    schema = KNOWN_BODY_CAPABILITIES[op].input_schema

    assert validate_capability_arguments(schema, {}) is not None


def test_brightness_is_an_integer_percentage_not_a_display_text_update() -> None:
    schema = KNOWN_BODY_CAPABILITIES[BODY_OP_DISPLAY_BRIGHTNESS].input_schema

    assert schema["properties"]["brightness"]["type"] == "integer"
    assert "text" not in schema["properties"]
