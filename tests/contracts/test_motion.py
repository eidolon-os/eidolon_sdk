import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.presentation.motion import StackChanHeadAction
from eidolon_sdk.grpc.eidolon_agent.v1 import eidolon_pb2 as pb


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "nod", "times": 0},
        {"action": "nod", "times": 4},
        {"action": "nod", "times": True},
        {"action": "nod", "times": 1.5},
        {"action": "nod", "times": "2"},
        {"action": "home", "times": 2},
        {"action": "lift_leg"},
        {"action": "nod", "angle": 180},
    ],
)
def test_unbounded_or_unsupported_commands_rejected(arguments):
    with pytest.raises(ValidationError):
        StackChanHeadAction.model_validate(arguments)


@pytest.mark.parametrize(
    "action", ["nod", "shake", "look_left", "look_right", "look_up", "look_down", "home", "stop"]
)
def test_typed_wire_round_trip_preserves_strict_integer(action):
    source = StackChanHeadAction(action=action)
    wire = pb.HeadMotionRequest(command_id="motion:1", **source.model_dump())
    received = pb.HeadMotionRequest.FromString(wire.SerializeToString())
    assert StackChanHeadAction(action=received.action, times=received.times) == source


def test_distinct_axes_and_gestures():
    def payload(action):
        return StackChanHeadAction(action=action).gesture_payload()

    assert payload("nod")["name"] != payload("shake")["name"]
    assert payload("look_left")["x"] < 0 < payload("look_right")["x"]
    assert payload("look_down")["y"] < 0 < payload("look_up")["y"]


def test_legacy_output_plan_omits_new_profile():
    from eidolon_sdk.biz.presentation import OutputSelection, SessionOutputPlan

    plan = SessionOutputPlan(
        session_id="s", policy_revision=1, outputs=OutputSelection(motion=True)
    )
    assert "motion_profile" not in plan.model_dump(mode="json")
    opted_in = plan.model_copy(update={"motion_profile": "stackchan.head.v1"})
    assert opted_in.model_dump(mode="json")["motion_profile"] == "stackchan.head.v1"
