"""Canonical Body Mesh bindings: which Companion answers through which Body.

The vocabulary lives here rather than in the Kernel because it is read by more
than its writer. A Companion is a lasting identity and a Body is a replaceable
carrier, so the relation between them is a first-class resource rather than a
``companion_id`` column on a device row — that is the whole reason this module
exists, and it is what makes an assignment survive a device being re-claimed.

Two things the frozen contract deliberately does *not* carry, recorded here so
the next reader does not go looking for them:

``selection_provenance`` is not on ``ReplaceAssignment``. Why a Body ended up
with no Companion — the Owner cleared it, the Companion was put away, a policy
reconcile released it — is not something a caller may assert. It follows from
*which* caller made the change, so the writing authority derives it. A caller
that could name its own provenance would be making a claim, not stating a fact.

``policy_refs`` is on the command and, on every Host today, is empty. Nothing in
this product defines a resource policy, and nothing evaluates one. The field
stays because the canonical contract has it and a Host that grows a policy
engine must not need a wire change; what must not happen is a client naming
refs no evaluator reads, which reads like a constraint and enforces nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .lifecycle import DeviceRef, WireEnum, _IDENTIFIER


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


#: An ``Identifier`` in the canonical common schema.
_Identifier = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)


#: The one Body endpoint every mounted device has until a Manifest declares its
#: own. Named rather than spelled inline so the derivation has one definition
#: and the reader of an identifier in a log can find where it came from.
#:
#: It is here rather than only in the producing authority because composing
#: ``<device_id>:body`` is what a consumer must do to *address* a Body at all.
#: A consumer that cannot import this word mirrors it instead, and then has to
#: invent a way to check the mirror — which is how one of them ended up
#: substring-matching the producer's source file.
DERIVED_ENDPOINT_ID = "body"


def _wire_instant(value: object) -> object:
    """Accept the wire form of an instant as well as the decoded one.

    The same rule :class:`WireEnum` restores for enums: a canonical model has to
    validate its own ``model_dump(mode="json")``. These models are strict, and a
    strict model reads a timestamp only as a ``datetime`` — so without this a
    document could be parsed from JSON bytes and never from the dictionary that
    same document decodes to, which is what every ASGI handler is given.
    """

    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return value.astimezone(UTC)


def _unique_tuple(value: object) -> object:
    value = tuple(value) if isinstance(value, list) else value
    if isinstance(value, tuple) and len(value) != len(set(value)):
        raise ValueError("canonical arrays are sets, not bags")
    return value


class AssignmentMode(WireEnum):
    """The only mode V1 defines.

    ``default`` means "when nothing else was said, this Companion answers here".
    Short-term possession — a guest taking over a speaker for one conversation —
    is a ``BodyLease``, which V1 deliberately does not define: it needs a TTL, an
    epoch and a fencing token, and pretending a persistent assignment can stand
    in for it is how a temporary takeover becomes permanent by accident.
    """

    DEFAULT = "default"


class SelectionProvenance(WireEnum):
    """Why this Body points where it points.

    The three ways a Body ends up answering as nobody are not the same event and
    must not read as one. A person who cleared it knows why it is quiet; a
    person whose Companion was put away is owed the sentence; and a Host that
    released it on its own has to be able to say so. Collapsing them into a null
    ``companion_id`` is exactly the state this product used to ship — a speaker
    that goes silent with no explanation is indistinguishable from a broken one.
    """

    USER_SELECTED = "user_selected"
    USER_CLEARED = "user_cleared"
    COMPANION_DELETED = "companion_deleted"
    POLICY_RECONCILED = "policy_reconciled"


class AssignmentCondition(WireEnum):
    """What is true about an assignment right now, in the authority's words."""

    REALIZED = "Realized"
    COMPANION_MISSING = "CompanionMissing"
    CAPABILITY_MISSING = "CapabilityMissing"
    POLICY_DENIED = "PolicyDenied"


class BodyTargetRef(_Model):
    """A Body addressed together with the assignment generation it was resolved at.

    The generation is not decoration. A runtime that resolved a target, then took
    a moment to build a session, must not act on an assignment that has since
    been replaced — the fence is the reason the reference carries it rather than
    naming the endpoint alone.
    """

    mount_id: str = _Identifier
    body_endpoint_id: str = _Identifier
    assignment_generation: int = Field(ge=1)


class ReplaceAssignment(_Model):
    """Point one Body endpoint at one Companion, or at nobody.

    Replace with a compare-and-swap, never delete-then-create: the intermediate
    state of the second form is a Body that briefly answers as nobody, and any
    reader that looked in that window would have seen an unassigned device that
    no one had unassigned.

    ``expected_assignment_revision`` is 0 for a Body that has never been
    assigned, which is why the minimum here is 0 and not 1.
    """

    body_endpoint_id: str = _Identifier
    expected_assignment_revision: int = Field(ge=0)
    companion_ref: str | None = Field(default=None, min_length=3, max_length=128, pattern=_IDENTIFIER)
    mode: AssignmentMode = AssignmentMode.DEFAULT
    policy_refs: tuple[str, ...] = ()

    @field_validator("policy_refs", mode="before")
    @classmethod
    def _policies(cls, value: object) -> object:
        value = tuple(value) if isinstance(value, list) else value
        if isinstance(value, tuple) and len(value) != len(set(value)):
            raise ValueError("assignment policy refs must be unique")
        return value


class ReplaceAssignmentResult(_Model):
    """What the authority committed.

    ``revision`` moves on every commit and is what the next writer compares
    against. ``generation`` moves only when the spec actually changes, so a
    consumer that fenced on it is not disturbed by a write that changed nothing
    it cares about.
    """

    assignment_id: str = _Identifier
    revision: int = Field(ge=1)
    generation: int = Field(ge=1)
    spec: dict[str, object]
    #: Left open, and not the same document as :class:`BodyAssignmentStatus`.
    #:
    #: This was going to be closed to the read path's shape in the same batch,
    #: on the reasoning that one ``status`` constrained in one place beats two.
    #: The canonical conformance vector says they are not one status:
    #: ``DF-BODY-REPLACE-ASSIGNMENT-RESULT-VALID`` in
    #: ``contracts/device_foundation/v1/examples/valid/body-mesh.json`` carries
    #: ``{"observed_generation": 0, "conditions": ["PendingRealization"]}`` —
    #: no ``effective_companion_id`` at all, a condition this module's vocabulary
    #: does not define, and an observed generation *behind* the committed one.
    #: That is the status of a resource whose realization lags its spec. The
    #: read path below is the status of one whose authority commits both in a
    #: single transaction. Closing this to that would make these bindings refuse
    #: a fixture this same package publishes, and the conformance runner would
    #: not notice: it checks fixtures against JSON Schema, never against these.
    status: dict[str, object]


class BodyAssignmentStatus(_Model):
    """What the writing authority says is *in force* for one Body, right now.

    Closed on purpose. Every field here was already being emitted and already
    being read; what was missing was anywhere to say so. A consumer that had to
    learn ``effective_companion_id`` from prose read the wrong field instead and
    started sessions under a Companion nobody had assigned — this type is what
    turns that prose into something that fails.

    A redundancy worth paying knowingly, rather than discovering later
    -----------------------------------------------------------------

    This whole object is a pure function of facts already in the same document:
    ``effective_companion_id`` is the assignment's ``companion_id`` when the
    endpoint is present and null otherwise, and ``observed_generation`` equals
    ``generation``. It carries no new information. It exists because spec/status
    is the shape of a canonical resource, and ``observed_generation`` is kept
    for the day a second actor realizes what a first actor committed.

    That day has not come. The producing authority says so itself — "there is no
    second actor to lag behind". So the pattern's benefit is still owed while its
    cost is already being paid, and the cost is exactly this: "who answers
    through this Body" is readable in two places in one document, and a consumer
    has to be told which one is the answer. Removing ``status`` would be a
    deviation from the canonical shape and is priced separately; what must not
    happen again is paying this without knowing it is being paid.
    """

    #: Equal to the assignment's ``generation`` on every Host today, for the
    #: reason above. Typed as its own field rather than asserted equal, because
    #: the day it can differ is the day a consumer must already be reading it.
    observed_generation: int = Field(ge=1)
    #: Who is answering, as opposed to who is assigned. Null for a Body whose
    #: device is no longer mounted: the assignment deliberately outlives the
    #: mount so a device that comes back comes back to the same Eidolon, which
    #: means the spec's ``companion_id`` is *not* the question "who answers
    #: here" — this is. Required rather than defaulted: a producer that stopped
    #: sending it must not read as a Body that answers as nobody.
    effective_companion_id: str | None = Field(min_length=1, max_length=64)
    #: Empty is a real answer, and it means "nothing is wrong here".
    #:
    #: The one local question this module was asked to settle: whether the
    #: vocabulary needs a value for a Body that is present and answering as
    #: nobody. It does not, for two separate reasons.
    #:
    #: A Body that was never assigned has no assignment document, so it has no
    #: ``conditions`` array for such a value to live in — a condition cannot
    #: describe the absence of the thing that would carry it.
    #:
    #: A Body that *was* assigned and is now quiet already says why, one field
    #: away on this same document: ``selection_provenance`` is ``user_cleared``,
    #: ``companion_deleted`` or ``policy_reconciled``, and ``user_selected`` with
    #: no Companion is refused at the authority. So a new condition would be a
    #: second spelling of a fact already stated here — the very redundancy
    #: documented above, added deliberately this time.
    conditions: tuple[AssignmentCondition, ...]

    @field_validator("conditions", mode="before")
    @classmethod
    def _conditions(cls, value: object) -> object:
        return _unique_tuple(value)


class BodyAssignment(_Model):
    """Which Companion answers through one Body, as the authority reports it.

    The read counterpart of :class:`ReplaceAssignmentResult`, and a wider
    document: it carries the facts needed to address this Body again, which a
    caller who just supplied them does not need back.

    ``selection_provenance`` is what lets a screen tell "you cleared this" apart
    from "the Eidolon it answered as was put away". Both leave the same null
    ``companion_id`` behind, and a speaker that goes quiet with no sentence
    attached is indistinguishable from a broken one.
    """

    operation: Literal["kernel.body-assignment"] = "kernel.body-assignment"
    #: Longer than a canonical ``Identifier`` because it is composed from one:
    #: ``assignment:<body_endpoint_id>``, and ``body_endpoint_id`` may itself
    #: use the full 128. Transcribed from what the authority can actually emit
    #: rather than re-derived, so that adopting this type changes no wire byte.
    assignment_id: str = Field(min_length=1, max_length=160)
    body_endpoint_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    endpoint_id: str = Field(min_length=1, max_length=64)
    owner_id: str = Field(min_length=1, max_length=64)
    #: What the spec says. Not who is answering — see
    #: :attr:`BodyAssignmentStatus.effective_companion_id`.
    companion_id: str | None = Field(min_length=1, max_length=64)
    selection_provenance: SelectionProvenance
    change_reason: str | None = Field(min_length=1, max_length=256)
    mode: AssignmentMode
    policy_refs: tuple[str, ...] = Field(max_length=16)
    #: Moves on every commit; what the next writer compares against.
    revision: int = Field(ge=1)
    #: Moves only when the spec changes, so a runtime that fenced a session on
    #: it is undisturbed by a write that changed nothing it depends on.
    generation: int = Field(ge=1)
    updated_at: datetime
    status: BodyAssignmentStatus

    @field_validator("policy_refs", mode="before")
    @classmethod
    def _policies(cls, value: object) -> object:
        return _unique_tuple(value)

    @field_validator("updated_at", mode="before")
    @classmethod
    def _updated_at(cls, value: object) -> object:
        return _wire_instant(value)


class BodyEndpoint(_Model):
    """One assignable Body, as the authority can currently describe it.

    Reading this answers both questions a session starts with — is this device
    this Owner's and mounted, and who answers through it — in one round trip.
    They were one field on a device mount once, which is why re-claiming a
    device silently forgot its Eidolon.
    """

    operation: Literal["kernel.body-endpoint"] = "kernel.body-endpoint"
    body_endpoint_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    owner_id: str = Field(min_length=1, max_length=64)
    endpoint_id: str = Field(min_length=1, max_length=64)
    #: Which mount this endpoint currently *is*, at the generation it was
    #: derived at — not a second copy of the mount, and a fence for anything
    #: that acts on this answer after the fact.
    device_ref: DeviceRef
    mount_revision: int = Field(ge=1)
    roles: tuple[
        Literal["body", "sensor", "actuator", "gateway", "controller"], ...
    ] = Field(min_length=1, max_length=8)
    assignment_policy: Literal["required", "optional", "forbidden"]
    risk_class: Literal["safe", "sensitive", "hazardous"]
    concurrency: Literal["shared", "exclusive", "leased"]
    #: ``derived`` says the Host filled in for a Manifest vocabulary that
    #: declares no endpoints. A consumer showing capability detail must not
    #: present a derived declaration as the device's own word.
    source: Literal["derived", "manifest"]
    #: False when the device this Body belongs to is no longer mounted. The
    #: assignment is deliberately not deleted with it: a device that comes back
    #: should come back to the Eidolon it answered as, and a deleted row cannot
    #: do that. This is why reading the spec instead of the status would start a
    #: session as an Eidolon on hardware that is not there.
    present: bool
    #: Null for a Body nobody has decided about yet. Required rather than
    #: defaulted, so a producer that stopped sending it is drift and not a Body
    #: that happens to be unassigned.
    assignment: BodyAssignment | None

    @field_validator("roles", mode="before")
    @classmethod
    def _roles(cls, value: object) -> object:
        return _unique_tuple(value)
