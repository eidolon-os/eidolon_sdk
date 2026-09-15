import json

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.presentation import (
    ExpressionPlan,
    OutputSelection,
    SessionOutputPlan,
    AssistantResponseCandidate,
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
