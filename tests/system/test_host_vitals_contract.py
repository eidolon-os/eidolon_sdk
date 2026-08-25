from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import ValidationError as PydanticValidationError

from eidolon_sdk.system.v1 import (
    HOST_VITALS_CONTRACT,
    HostVitalsWire,
    MeasurementWire,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "contracts/system/v1/host-vitals.schema.json"


def _validator() -> Draft202012Validator:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(document, format_checker=FormatChecker())


def _document() -> dict:
    return HostVitalsWire(
        operation="system.host-vitals",
        observed_at=datetime(2026, 8, 26, tzinfo=UTC),
        measurements=(
            MeasurementWire(
                name="temperature",
                value=48.6,
                unit="celsius",
                capacity=None,
                unavailable_reason=None,
            ),
            MeasurementWire(
                name="disk.state",
                value=None,
                unit="bytes",
                capacity=None,
                unavailable_reason="state path is unavailable",
            ),
        ),
    ).model_dump(mode="json")


def test_binding_and_schema_accept_the_same_complete_document() -> None:
    document = _document()

    _validator().validate(document)
    parsed = HostVitalsWire.model_validate(document)

    assert parsed.operation == "system.host-vitals"
    assert parsed.measurements[1].value is None
    assert parsed.measurements[1].unavailable_reason


def test_contract_identity_is_published_from_the_sdk() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert schema["$id"] == HOST_VITALS_CONTRACT
    assert HostVitalsWire.__module__.startswith("eidolon_sdk.system.v1")


def test_schema_and_binding_both_reject_unknown_wire_fields() -> None:
    document = _document()
    document["machine_health"] = "healthy"

    with pytest.raises(ValidationError):
        _validator().validate(document)
    with pytest.raises(PydanticValidationError):
        HostVitalsWire.model_validate(document)


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ((), "operation"),
        (("measurements", 0), "unavailable_reason"),
    ],
)
def test_schema_and_binding_both_reject_missing_required_fields(path, field) -> None:
    document = _document()
    target = document
    for component in path:
        target = target[component]
    del target[field]

    with pytest.raises(ValidationError):
        _validator().validate(document)
    with pytest.raises(PydanticValidationError):
        HostVitalsWire.model_validate(document)


def test_absence_is_not_serialised_as_zero_or_healthy() -> None:
    document = _document()
    missing = document["measurements"][1]

    assert missing["value"] is None
    assert "healthy" not in missing
    assert "concern" not in missing
