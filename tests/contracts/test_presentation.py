import json

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.presentation import (
    ExpressionPlan,
    OutputSelection,
    SessionOutputPlan,
    AssistantResponseCandidate,
)
from eidolon_sdk.biz.presentation.device import (
    DeviceOutputConfiguration,
    ReadDeviceOutputPolicy,
)


def plan(**overrides):
    return dict(
        presentation_id="p1",
        response_id="r1",
        max_duration_ms=1500,
        steps=[dict(gesture="affirm", duration_ms=1000)],
        **overrides,
    )


def test_plan_round_trip_and_no_board_specific_profile():
    valid = ExpressionPlan.model_validate(plan())
    assert ExpressionPlan.from_wire(valid.model_dump_json()) == valid
    data = plan()
    data["profile"] = "eidolon.expression.box3.v1"
    with pytest.raises(ValidationError):
        ExpressionPlan.model_validate(data)


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [dict(gesture="affirm", duration_ms=1000, at_ms=600)],
        [
            dict(gesture="affirm", duration_ms=1000),
            dict(gesture="ponder", at_ms=500, duration_ms=500),
        ],
        [dict(gesture="arbitrary_script", duration_ms=500)],
        [dict(gesture="affirm", duration_ms=True)],
        [dict(gesture="affirm", duration_ms=500, intensity=float("nan"))],
        [dict(gesture="affirm", duration_ms=500, intensity=1.1)],
        [dict(gesture="affirm", duration_ms=150, at_ms=i * 150) for i in range(9)],
    ],
)
def test_invalid_plans_are_rejected(steps):
    data = plan()
    data["steps"] = steps
    with pytest.raises(ValidationError):
        ExpressionPlan.model_validate(data)


def test_bounded_wire_and_unknown_fields():
    with pytest.raises(ValueError, match="PLAN_TOO_LARGE"):
        ExpressionPlan.from_wire(" " * 2049)
    with pytest.raises(ValidationError):
        ExpressionPlan.from_wire(json.dumps(plan(script="do anything")))


def test_policy_intersection_never_enlarges_capability():
    capable = OutputSelection(speech=True, expression=True)
    silent = OutputSelection(expression=True, motion=True)
    selected = capable.restrict(silent)
    assert selected == OutputSelection(expression=True)
    assert selected.restrict(OutputSelection()) == OutputSelection()


def test_no_output_and_missing_face_profile_fail_at_negotiation():
    for outputs, profile in [
        (OutputSelection(), None),
        (OutputSelection(expression=True), None),
        (OutputSelection(speech=True), "eidolon.face.v1"),
    ]:
        with pytest.raises(ValidationError):
            SessionOutputPlan(
                session_id="s1", policy_revision=1, outputs=outputs, expression_profile=profile
            )
    assert SessionOutputPlan(
        session_id="s1",
        policy_revision=1,
        outputs=OutputSelection(expression=True),
        expression_profile="eidolon.face.v1",
    )


def device_ref():
    return dict(
        device_instance_id="device-instance-" + "a1" * 32,
        owner_domain_id="owner-f774cf8e1b667eb0ca7b",
        owner_domain_generation=3,
        claim_generation=1,
        trust_epoch=1,
    )


def test_undecided_output_policy_is_not_an_empty_one():
    """``None`` is an open question; an empty selection is the Owner's answer."""

    undecided = DeviceOutputConfiguration.model_validate(
        dict(device_ref=device_ref(), capabilities=dict(speech=True, expression=True))
    )
    assert undecided.policy is None
    denied = DeviceOutputConfiguration.model_validate(
        dict(
            device_ref=device_ref(),
            capabilities=dict(speech=True, expression=True),
            policy=dict(revision=4, allowed={}),
        )
    )
    assert denied.policy is not None and denied.policy.allowed == OutputSelection()
    assert denied != undecided
    assert DeviceOutputConfiguration.model_validate_json(denied.model_dump_json()) == denied


def test_output_policy_query_carries_only_the_device_it_asks_about():
    assert ReadDeviceOutputPolicy.model_validate(dict(device_ref=device_ref()))
    for smuggled in ({"allowed": {"speech": True}}, {"owner_id": "owner_1"}):
        with pytest.raises(ValidationError):
            ReadDeviceOutputPolicy.model_validate(dict(device_ref=device_ref(), **smuggled))


def test_model_cannot_specify_device_or_authority():
    with pytest.raises(ValidationError):
        AssistantResponseCandidate.model_validate(
            dict(presentation=dict(intent="confirm", outcome_ref="result-1"), device_id="box3")
        )


def test_exported_artifacts_match_sdk_types():
    from pathlib import Path
    from eidolon_sdk.biz.presentation.export import artifacts

    root = Path(__file__).resolve().parents[2] / "contracts/presentation/v1"
    for name, content in artifacts().items():
        assert (root / name).read_text() == content, name


def test_boolean_is_not_an_intensity():
    data = plan()
    data["steps"][0]["intensity"] = True
    with pytest.raises(ValidationError):
        ExpressionPlan.model_validate(data)


@pytest.mark.parametrize("expression", [False, True])
def test_explicit_contract_requires_policy_independently_of_face(expression):
    from eidolon_sdk.biz.presentation.negotiation import (
        output_policy_required,
        validate_output_contract,
    )

    caps = OutputSelection(speech=True, dialogue_text=True, expression=expression)
    manifest = {
        "properties": [
            {
                "name": "output.contract",
                "writable": False,
                "schema": {"type": "string", "const": "eidolon.outputs.v1"},
            }
        ]
    }
    validate_output_contract(manifest)
    assert output_policy_required(caps, manifest=manifest)
    assert output_policy_required(caps, requirement=True)
    assert output_policy_required(caps) == expression


@pytest.mark.parametrize("value", [None, False, "eidolon.outputs.v2"])
def test_invalid_contract_never_restores_legacy_defaults(value):
    from eidolon_sdk.biz.presentation.negotiation import (
        output_policy_required,
        validate_output_contract,
    )

    manifest = {
        "properties": [
            {
                "name": "output.contract",
                "writable": False,
                "schema": {"type": "string", "const": value},
            }
        ]
    }
    assert output_policy_required(OutputSelection(speech=True), manifest=manifest)
    with pytest.raises(ValueError, match="OUTPUT_CONTRACT"):
        validate_output_contract(manifest)
