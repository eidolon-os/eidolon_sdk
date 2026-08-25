"""The setup descriptor is a canonical contract, not two hand-written field tables.

Every DTO in the commissioning act already had one definition here and golden
vectors both ends test against — except this one. The descriptor was written by
hand in the firmware and read by hand in the phone app, and the field table was
kept in step by a person comparing two files. It drifted the way that always
drifts: an unbounded setup window was encoded as `expires_in_seconds: 0` by the
device and refused as an impossible duration by the controller, so every device
out of the box was rejected with "the description this device returned does not
match the v1 contract" and neither side was wrong about its own half.

So the rules below are the contract, and the two ends are held to them by a
golden vector rather than by review.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from eidolon_sdk.device_foundation.v1 import (
    SetupDescriptor,
    SetupDescriptorTrust,
    setup_descriptor_from_json,
    setup_descriptor_to_json,
)


SDK_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = SDK_ROOT / "contracts" / "device_foundation" / "v1"
GOLDEN_PATH = CONTRACT_ROOT / "golden" / "setup-descriptor.json"
COMMON_SCHEMA_ID = (
    "https://contracts.eidolon.live/device-foundation/v1/common/schemas.schema.json"
)


def _runner():
    path = CONTRACT_ROOT / "conformance" / "run.py"
    spec = importlib.util.spec_from_file_location("device_foundation_v1_conformance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _golden() -> dict[str, object]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _validator():
    runner = _runner()
    _, registry = runner._load_schemas()
    return Draft202012Validator(
        {"$ref": f"{COMMON_SCHEMA_ID}#/$defs/SetupDescriptor"}, registry=registry
    )


def test_conformance_runner_checks_the_setup_descriptor_vector() -> None:
    assert _runner().run()["setup_descriptor_vectors"] == 1


def test_golden_vector_is_the_field_table_both_ends_answer_to() -> None:
    """The vector names the fields, so a field added only here still goes red.

    Both clients assert their own field set against this list. Adding a field to
    the schema and forgetting the list — or the list and forgetting a client —
    fails somewhere rather than shipping as a descriptor one end cannot read.
    """

    golden = _golden()
    schema = json.loads((CONTRACT_ROOT / "common" / "schemas.schema.json").read_text())
    definition = schema["$defs"]["SetupDescriptor"]
    assert golden["required_fields"] == definition["required"]
    assert sorted(golden["required_fields"] + golden["optional_fields"]) == sorted(
        definition["properties"]
    )
    for shape in ("bounded_window", "no_deadline"):
        assert set(golden[shape]["descriptor"]) >= set(golden["required_fields"])


def test_golden_shapes_are_valid_and_canonical() -> None:
    validator = _validator()
    for shape in ("bounded_window", "no_deadline"):
        value = _golden()[shape]["descriptor"]
        validator.validate(value)
        assert _runner().canonical_bytes(value).decode("utf-8") == _golden()[shape][
            "canonical_utf8"
        ]


def test_an_offer_that_does_not_end_names_no_duration() -> None:
    golden = _golden()
    assert "expires_in_seconds" not in golden["no_deadline"]["descriptor"]
    assert golden["bounded_window"]["descriptor"]["expires_in_seconds"] >= 1


@pytest.mark.parametrize("encoded", [0, -1, 1.5, None, "600", True])
def test_no_number_may_stand_in_for_no_deadline(encoded: object) -> None:
    """0 was the sentinel that broke commissioning on every factory device.

    The type has no room for it: a duration that exists is a positive integer,
    and the only way to say an offer does not end is to leave the field out.
    """

    value = dict(_golden()["bounded_window"]["descriptor"])
    value["expires_in_seconds"] = encoded
    assert not _validator().is_valid(value)


def test_a_field_nobody_declared_is_not_a_descriptor() -> None:
    value = dict(_golden()["bounded_window"]["descriptor"])
    value["expires_at"] = "2026-08-25T00:00:00Z"
    assert not _validator().is_valid(value)


def test_python_binding_round_trips_the_golden_bytes() -> None:
    runner = _runner()
    for shape in ("bounded_window", "no_deadline"):
        golden = _golden()[shape]
        descriptor = setup_descriptor_from_json(golden["descriptor"])
        assert isinstance(descriptor, SetupDescriptor)
        rendered = setup_descriptor_to_json(descriptor)
        assert runner.canonical_bytes(rendered).decode("utf-8") == golden["canonical_utf8"]
    assert setup_descriptor_from_json(
        _golden()["no_deadline"]["descriptor"]
    ).expires_in_seconds is None


def test_python_binding_refuses_a_duration_that_is_not_one() -> None:
    fields = dict(_golden()["bounded_window"]["descriptor"])
    # Including an explicit null: a key written with nothing in it is a
    # producer reaching for a stand-in, not the absence that means "never".
    for encoded in (0, -1, 1.5, "600", True, None):
        broken = dict(fields)
        broken["expires_in_seconds"] = encoded
        with pytest.raises(ValueError):
            setup_descriptor_from_json(broken)


def test_python_binding_carries_the_two_trust_levels_the_wire_has() -> None:
    assert {member.value for member in SetupDescriptorTrust} == set(
        _golden()["trust_values"]
    )


def test_every_binding_language_declares_the_whole_field_table() -> None:
    """A field added to the contract but not to one binding is caught here.

    The C++ and Dart bindings are copied byte-for-byte into the firmware and the
    app, so a field missing from either is a field one end of the act cannot
    see. Reading the rendered bindings is the only place that can tell.
    """

    golden = _golden()
    dart = (CONTRACT_ROOT / "generated" / "dart" / "device_foundation_v1.dart").read_text()
    cpp = (
        CONTRACT_ROOT / "generated" / "cpp" / "device_foundation_v1_generated.h"
    ).read_text()
    for field in golden["required_fields"] + golden["optional_fields"]:
        assert f"'{field}'" in dart, field
        assert f'"{field}"' in cpp, field


def test_generation_has_no_drift() -> None:
    result = subprocess.run(
        [sys.executable, str(CONTRACT_ROOT / "generation" / "generate.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
