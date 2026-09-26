"""Host-internal role-group stream. The authenticated Channel owns media IO.

One connection owns one scene; it must stop every prepared endpoint if this
connection fails. A played receipt means physical presentation drained, never
model DONE, synthesis completion or an HTTP success. No device credentials or
raw audio are transported here. Service authentication is required separately.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from eidolon_sdk.biz.dialogue_control import CommittedTurnDecision, TurnCommitBoundary

from .coordination import CoordinationSelection, Identifier

ROLE_GROUP_STREAM_PATH = "/api/admin/role-groups/stream"
MAX_FRAME_BYTES = 131072


class Frame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OpenScene(Frame):
    type: Literal["open"]
    owner_id: Identifier
    selection: CoordinationSelection
    # Explicit simulation policy until a production adjudicator is configured.
    mock_order: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def known_candidates(self) -> Self:
        if len(set(self.mock_order)) != len(self.mock_order):
            raise ValueError("duplicate mock decision candidate")
        if not set(self.mock_order) <= {m.companion_id for m in self.selection.members}:
            raise ValueError("mock decision candidate is not a scene member")
        return self


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
