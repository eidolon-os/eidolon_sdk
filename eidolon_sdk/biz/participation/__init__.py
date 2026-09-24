"""Participation decision v1: model-neutral proposals, never execution grants.

Bounds are wire safety limits, not a promise of a model's token capacity.
Adapters must reject context beyond their own limits rather than truncate it.
Owner authentication, current-state checks and durable dedup belong to callers.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Action = Literal["respond", "clarify", "wait", "finish"]
Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=512, pattern=r"\S")]
Text = Annotated[str, Field(strict=True, max_length=32768)]
Revision = Annotated[int, Field(strict=True, ge=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Message(Contract):
    message_id: Identifier
    author_kind: Literal["user", "companion", "system"]
    author_id: Identifier
    text: Text


class Context(Contract):
    summary: Text = ""
    recent_messages: Annotated[tuple[Message, ...], Field(max_length=64)] = ()
    pending_requirements: Annotated[tuple[Text, ...], Field(max_length=32)] = ()


class Candidate(Contract):
    companion_id: Identifier
    description: Annotated[str, Field(strict=True, max_length=4096)]


class Constraints(Contract):
    allowed_actions: Annotated[tuple[Action, ...], Field(min_length=1, max_length=4)] = (
        "respond",
        "clarify",
        "wait",
        "finish",
    )
    max_next_speakers: Annotated[int, Field(strict=True, ge=1, le=64)] = 1

    @model_validator(mode="after")
    def unique_actions(self) -> Self:
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ValueError("DUPLICATE_ALLOWED_ACTION")
        return self


class Snapshot(Contract):
    schema_version: Literal[1] = 1
    decision_id: Identifier
    context_ref: Identifier
    context_version: Revision
    membership_revision: Revision
    cancellation_epoch: Revision

    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, value):
        if isinstance(value, dict) and "schema_version" in value:
            if type(value["schema_version"]) is not int:
                raise ValueError("SCHEMA_VERSION_MUST_BE_INTEGER")
        return value


class DecisionRequest(Snapshot):
    trigger: Message
    context: Context = Field(default_factory=Context)
    candidates: Annotated[tuple[Candidate, ...], Field(max_length=64)]
    constraints: Constraints = Field(default_factory=Constraints)
    timeout_ms: Annotated[int, Field(strict=True, ge=1, le=60000)]

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        ids = [candidate.companion_id for candidate in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("DUPLICATE_CANDIDATE")
        # Bound the whole snapshot too, not just each individual message.
        size = len(self.trigger.text) + len(self.context.summary)
        size += sum(len(message.text) for message in self.context.recent_messages)
        size += sum(map(len, self.context.pending_requirements))
        size += sum(len(candidate.description) for candidate in self.candidates)
        if size > 131072:
            raise ValueError("CONTEXT_TOO_LARGE")
        return self


class Proposal(Contract):
    action: Action
    participants: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if len(set(self.participants)) != len(self.participants):
            raise ValueError("DUPLICATE_PARTICIPANT")
        count = len(self.participants)
        if (
            self.action == "respond"
            and count == 0
            or self.action == "clarify"
            and count != 1
            or self.action in {"wait", "finish"}
            and count != 0
        ):
            raise ValueError("PARTICIPANTS_DO_NOT_MATCH_ACTION")
        return self


class DecisionResult(Snapshot):
    status: Literal["decided", "abstained"]
    proposal: Proposal | None = None
    policy_version: Identifier
    model_version: Identifier

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if (self.status == "decided") != (self.proposal is not None):
            raise ValueError("PROPOSAL_DOES_NOT_MATCH_STATUS")
        return self


def validate_proposal(request: DecisionRequest, result: DecisionResult) -> None:
    """Reject a stale/illegal proposal. This does not authorize its execution.

    Callers must additionally compare request revisions to CURRENT authority
    state, check deadline/budget, and atomically issue at most one turn permit.
    """
    for key in Snapshot.model_fields:
        if getattr(request, key) != getattr(result, key):
            raise ValueError("DECISION_SNAPSHOT_MISMATCH")
    proposal = result.proposal
    if proposal is None:
        return
    if proposal.action not in request.constraints.allowed_actions:
        raise ValueError("ACTION_NOT_ALLOWED")
    candidates = {candidate.companion_id for candidate in request.candidates}
    if not set(proposal.participants) <= candidates:
        raise ValueError("PARTICIPANT_OUTSIDE_CANDIDATES")
    if len(proposal.participants) > request.constraints.max_next_speakers:
        raise ValueError("TOO_MANY_PARTICIPANTS")
