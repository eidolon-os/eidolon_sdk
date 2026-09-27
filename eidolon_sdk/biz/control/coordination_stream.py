"""Host-internal role-group stream. The authenticated Channel owns media IO.

One connection owns one scene; it must stop every prepared endpoint if this
connection fails. A reply receipt declares its completion basis: native LiveKit playout or a
device acknowledgement. Neither is inferred from model DONE or HTTP success. No device credentials or
raw audio are transported here. Service authentication is required separately.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from eidolon_sdk.biz.dialogue_control import CommittedTurnDecision, TurnCommitBoundary

from .coordination import (
    CoordinationSelection, Identifier, STOP_EXECUTION_TIMEOUT, STOP_RECEIPT_TIMEOUT,
)

ROLE_GROUP_STREAM_PATH = "/api/admin/role-groups/stream"
MAX_FRAME_BYTES = 131072


class Frame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OpenScene(Frame):
    schema_version: Literal[2] = 2
    type: Literal["open"]
    owner_id: Identifier
    selection: CoordinationSelection


class Press(Frame):
    type: Literal["press"]
    capture_id: Identifier


class Release(Frame):
    type: Literal["release"]
    capture_id: Identifier


class Transcript(Frame):
    type: Literal["transcript"]
    capture_id: Identifier
    text: Annotated[str, Field(strict=True, max_length=32768)]
    commitment: dict | None = None

    @model_validator(mode="after")
    def committed_ptt(self) -> Self:
        if not self.text.strip():
            if self.commitment is not None:
                raise ValueError("empty capture must not claim a committed transcript")
            return self
        decision = CommittedTurnDecision.from_metadata(self.commitment)
        if decision.evidence.boundary != TurnCommitBoundary.PTT_SEGMENT:
            raise ValueError("role-group input requires a PTT commit")
        if not decision.matches_text(self.text):
            raise ValueError("committed transcript mismatch")
        return self


class Receipt(Frame):
    type: Literal["receipt"]
    request_id: Identifier
    device_id: Identifier
    result: Literal["completed", "failed"]
    completion_basis: Literal["device_ack", "native_playout"] = "device_ack"
    error_code: Annotated[str, Field(strict=True, max_length=128)] = ""


class Speaking(Frame):
    type: Literal["speaking"]
    turn_id: Identifier
    device_id: Identifier


class Close(Frame):
    type: Literal["close"]


ClientFrame = Annotated[
    Press | Release | Transcript | Receipt | Speaking | Close, Field(discriminator="type")
]
CLIENT_FRAME = TypeAdapter(ClientFrame)


class ServerFrame(Frame):
    stream_id: Identifier
    session_id: Identifier


class Prepared(ServerFrame):
    type: Literal["prepared"]
    policy: Literal["semantic-step-v2"]
    physical_devices_ready: Literal[False]


Epoch = Annotated[int, Field(strict=True, ge=0)]


class Capturing(ServerFrame):
    type: Literal["capturing"]
    capture_id: Identifier
    epoch: Epoch


class Stop(ServerFrame):
    # PTT stops share the Channel's immediate local operation. Cleanup stops do not.
    capture_id: Identifier | None = None
    type: Literal["stop"]
    request_id: Identifier
    device_id: Identifier
    epoch: Epoch


class ReplyFrame(ServerFrame):
    request_id: Identifier
    turn_id: Identifier
    device_id: Identifier
    epoch: Epoch

    @model_validator(mode="after")
    def request_is_turn(self) -> Self:
        if self.request_id != self.turn_id:
            raise ValueError("reply request must match turn")
        return self


class ReplyStart(ReplyFrame):
    type: Literal["reply_start"]
    companion_id: Identifier


class ReplyDelta(ReplyFrame):
    type: Literal["reply_delta"]
    text: Annotated[str, Field(strict=True, max_length=32768)]


class ReplyEnd(ReplyFrame):
    type: Literal["reply_end"]


class SceneState(ServerFrame):
    type: Literal["state"]
    capture_id: Identifier
    state: Annotated[str, Field(strict=True, max_length=64)]
    members: dict[Identifier, Annotated[str, Field(strict=True, max_length=64)]]
    epoch: Epoch
    outcome: Literal["waiting", "finished", "clarification", "budget_exhausted", "abstained", "error", "empty_input"] = "waiting"
    error_code: Annotated[str, Field(strict=True, max_length=128)] = ""


SERVER_FRAME = TypeAdapter(
    Annotated[
        Prepared | Capturing | Stop | ReplyStart | ReplyDelta | ReplyEnd | SceneState,
        Field(discriminator="type"),
    ]
)
