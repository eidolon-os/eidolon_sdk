"""Bounded StackChan head commands, distinct from conversational expression."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from . import Contract, Identifier

STACKCHAN_HEAD_PROFILE = "stackchan.head.v1"
STACKCHAN_HEAD_TOOL = "stackchan_head"


class StackChanHeadAction(Contract):
    action: Literal[
        "nod", "shake", "look_left", "look_right", "look_up", "look_down", "home", "stop"
    ]
    times: Annotated[int, Field(strict=True, ge=1, le=3)] = 1

    @model_validator(mode="after")
    def repetitions(self):
        if self.action not in {"nod", "shake"} and self.times != 1:
            raise ValueError("REPETITIONS_ONLY_FOR_NOD_OR_SHAKE")
        return self

    def gesture_payload(self) -> dict:
        # Directions follow the existing board's normalized robot-relative axes.
        # Physical sign/installation remains a per-unit acceptance check.
        directions = {
            "look_left": (-0.2, 0.0),
            "look_right": (0.2, 0.0),
            "look_up": (0.0, 0.35),
            "look_down": (0.0, -0.35),
        }
        if self.action in directions:
            x, y = directions[self.action]
            return {"name": "glance", "times": 1, "x": x, "y": y, "return_ms": 650}
        if self.action == "stop":
            raise ValueError("STOP_IS_NOT_A_GESTURE")
        return {"name": self.action, "times": self.times}


class MotionRequest(Contract):
    turn_id: Identifier
    command_id: Identifier
    action: StackChanHeadAction


class MotionReceipt(Contract):
    command_id: Identifier
    status: Literal["completed", "cancelled", "rejected", "failed"]
    reason: Annotated[str, Field(max_length=96)] = ""
    # Completion of the software sequence is not measured physical arrival.
    completion_basis: Literal["unconfirmed", "software_sequence", "drive_stopped"] = "unconfirmed"
