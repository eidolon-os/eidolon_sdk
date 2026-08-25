"""The Companion vocabulary, defined once for everyone who consumes it.

Data is the authority for what a Companion *is*; this module is where the words
it publishes are written down once so that consumers stop each keeping a copy.
Before this file the four lifecycle values were spelled out seven times in
Python and three times in JSON Schema across four repositories, and one of those
copies had drifted to a different set entirely — which is the failure this file
exists to make impossible rather than merely unlikely.

Why here and not in ``eidolon_data``: the producer already publishes JSON
Schemas, and a consumer that wants the values as *code* would have to either
parse those at import time or keep a copy. ``eidolon_data``, ``eidolon_admin``,
``eidolon_channel`` and ``eidolon_agent`` all already depend on this package, so
one import reaches all of them. ``eidolon_kernel`` deliberately does not depend
on it and keeps a vendored external schema with a mirror test instead; that is a
trust boundary, not an oversight, and it stays.

The values are the producer's, and this file is downstream of that decision. A
change here that Data has not made is a lie about what a Host will send.
"""

from __future__ import annotations

from typing import Literal

#: Where a Companion is in its life, as the Companion authority publishes it.
#:
#: Four values rather than a boolean, because "the Owner archived it" and "it
#: cannot run right now" are different things to say to a person, and folding
#: them was the conflation the identity contract was changed to remove.
LIFECYCLE_ACTIVE = "active"
#: On its way out: still answerable, no longer accepting new work.
LIFECYCLE_RETIRING = "retiring"
#: The Owner put it away. Its memory is kept; it does not answer.
LIFECYCLE_ARCHIVED = "archived"
#: Deletion is under way. Terminal, and not a state anything recovers from.
LIFECYCLE_DELETING = "deleting"

COMPANION_LIFECYCLE_STATES: tuple[str, ...] = (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_RETIRING,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_DELETING,
)

#: For a model field. Ordered as above so a generated document reads the same
#: way whoever emits it.
CompanionLifecycleState = Literal["active", "retiring", "archived", "deleting"]

#: Which Companions the Owner's default pointer may name. A guard belongs to
#: another product line (see docs/跨系统/Guard产品线边界.md) and never answers
#: for an Owner who named nobody, so it is excluded here rather than in each
#: caller that asks.
DEFAULT_ELIGIBLE_LIFECYCLE_STATES: tuple[str, ...] = (LIFECYCLE_ACTIVE,)

#: Which state a Companion may move to from where. Written down because the
#: order is the safety property, not a formality: archiving without retiring
#: first would skip the step where new sessions and Body assignments stop being
#: accepted, and a Companion can be archived while something is still talking to
#: it only if that step never ran.
#:
#: ``deleting`` is terminal and reachable only from ``archived``: hard deletion is
#: a separate data-governance workflow, and nothing comes back from it.
COMPANION_LIFECYCLE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    LIFECYCLE_ACTIVE: (LIFECYCLE_RETIRING,),
    LIFECYCLE_RETIRING: (LIFECYCLE_ARCHIVED, LIFECYCLE_ACTIVE),
    LIFECYCLE_ARCHIVED: (LIFECYCLE_ACTIVE, LIFECYCLE_DELETING),
    LIFECYCLE_DELETING: (),
}

def companion_lifecycle_path(current: str, target: str) -> tuple[str, ...]:
    """The states to ask for, in order, to get from ``current`` to ``target``.

    Empty when it is already there. ``None``-free: an unreachable target raises,
    because a caller that got an empty answer for "impossible" would read it as
    "nothing to do".

    This exists so that no consumer writes down "archiving means retiring first".
    That sentence is already written, once, in the table above — a projection
    that repeated it would be a second copy of the state machine, and the two
    would disagree the day a state is added between them. Shortest path, so a
    graph that grows a shortcut is taken without anyone editing a caller.

    ``deleting`` is reachable in this graph and no product surface offers it;
    keeping the walk faithful to the table is what lets the surfaces decide that,
    rather than this function pretending the edge is not there.
    """

    if current == target:
        return ()
    seen = {current}
    queue: list[tuple[str, tuple[str, ...]]] = [(current, ())]
    while queue:
        state, route = queue.pop(0)
        for nxt in COMPANION_LIFECYCLE_TRANSITIONS.get(state, ()):
            if nxt in seen:
                continue
            walked = (*route, nxt)
            if nxt == target:
                return walked
            seen.add(nxt)
            queue.append((nxt, walked))
    raise ValueError(f"no companion lifecycle path from {current!r} to {target!r}")


#: Why a lifecycle command was refused, in a word a consumer can act on.
#:
#: Same reasoning as ``PersonaConflictCode``: these refusals reach a person
#: through two process boundaries, and they call for different things. "Someone
#: changed it while you were deciding" is worth a re-read; "this Companion is the
#: one your Eidolon answers as, name a replacement" is a question for the person;
#: "it is already archived" is a success for anyone retrying.
CompanionLifecycleConflictCode = Literal[
    #: The caller's revision is older than the aggregate's, and the state it
    #: asked for is not the state it is in.
    "revision_stale",
    #: The move is not one this state allows — archiving something that was never
    #: retired, restoring something that is being deleted.
    "transition_not_allowed",
    #: This Companion is the Owner's default and archiving it would leave the
    #: pointer at something that cannot answer. The caller must name a
    #: replacement in the same request.
    "default_replacement_required",
    #: A replacement was named and cannot take the role: it is not this Owner's,
    #: not active, is the Companion being retired, or is a kind that never
    #: answers for an unaddressed request.
    "default_replacement_ineligible",
    #: There is nobody else to hand the role to. Archiving the only Companion an
    #: Owner has would leave them with an Eidolon that cannot answer at all.
    "last_active_companion",
    #: The Companion is not this Owner's, or is not there. One code for both, so
    #: an id cannot be probed for existence.
    "not_found",
]

__all__ = [
    "COMPANION_LIFECYCLE_STATES",
    "COMPANION_LIFECYCLE_TRANSITIONS",
    "CompanionLifecycleConflictCode",
    "DEFAULT_ELIGIBLE_LIFECYCLE_STATES",
    "LIFECYCLE_ACTIVE",
    "LIFECYCLE_ARCHIVED",
    "LIFECYCLE_DELETING",
    "LIFECYCLE_RETIRING",
    "CompanionLifecycleState",
    "companion_lifecycle_path",
]
