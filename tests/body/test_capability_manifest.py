from __future__ import annotations

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.body import (
    CapabilityDeclaration,
    CapabilityManifest,
    validate_capability_arguments,
)


def _capability(**overrides):
    data = {
        "name": "camera.capture",
        "version": 1,
        "description": "Capture one image from this device.",
        "input_schema": {
            "type": "object",
            "properties": {
                "quality": {"type": "string", "enum": ["low", "high"]},
            },
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "properties": {"asset_id": {"type": "string"}},
            "required": ["asset_id"],
            "additionalProperties": False,
        },
    }
    data.update(overrides)
    return data


def test_strict_dynamic_capability_contract_accepts_unknown_namespaced_op() -> None:
    capability = CapabilityDeclaration.model_validate(_capability())

    assert capability.name == "camera.capture"
    assert capability.version == 1
    assert capability.input_schema["properties"]["quality"]["enum"] == ["low", "high"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "CAPTURE"},
        {"version": 0},
        {"description": ""},
        {"risk_level": "low"},
        {"input_schema": {"type": "string"}},
        {"input_schema": {"type": "object", "oneOf": []}},
    ],
)
def test_capability_contract_rejects_legacy_or_policy_fields(overrides) -> None:
    with pytest.raises(ValidationError):
        CapabilityDeclaration.model_validate(_capability(**overrides))


def test_manifest_rejects_duplicate_name() -> None:
    with pytest.raises(ValidationError, match="duplicate capability"):
        CapabilityManifest.model_validate(
            {"capabilities": [_capability(), _capability()]}
        )


def test_manifest_rejects_same_name_with_multiple_contract_versions() -> None:
    with pytest.raises(ValidationError, match="duplicate capability"):
        CapabilityManifest.model_validate(
            {"capabilities": [_capability(), _capability(version=2)]}
        )


def test_runtime_argument_validation_uses_the_declared_schema() -> None:
    capability = CapabilityDeclaration.model_validate(_capability())

    assert validate_capability_arguments(
        capability.input_schema, {"quality": "high"}
    ) is None
    assert "enum" in str(
        validate_capability_arguments(
            capability.input_schema, {"quality": "ultra"}
        )
    )
    assert "unexpected" in str(
        validate_capability_arguments(
            capability.input_schema, {"extra": True}
        )
    )
