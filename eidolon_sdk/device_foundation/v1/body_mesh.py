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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .lifecycle import WireEnum, _IDENTIFIER


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


#: An ``Identifier`` in the canonical common schema.
_Identifier = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)


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
    status: dict[str, object]
