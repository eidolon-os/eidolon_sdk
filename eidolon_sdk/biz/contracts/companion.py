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

__all__ = [
    "COMPANION_LIFECYCLE_STATES",
    "DEFAULT_ELIGIBLE_LIFECYCLE_STATES",
    "LIFECYCLE_ACTIVE",
    "LIFECYCLE_ARCHIVED",
    "LIFECYCLE_DELETING",
    "LIFECYCLE_RETIRING",
    "CompanionLifecycleState",
]
