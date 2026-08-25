"""How an Eidolon surface says no, defined once for everyone who says it.

A refusal is a contract, not an error string. Before this module every
Owner-facing surface invented its own shape and every client re-guessed it: the
per-Realm memory surface answered ``{"detail": "<sentence>"}``, Admin's internal
ABI answered a structured failure, the LAN management surface replaced that with
a *different* sentence of its own and kept only one field of it, and the phone
could tell exactly one refusal apart from the rest — a lost race, because 409
was the one status it had been taught. Everything else, from "this Host was
never given the credential" to "that service is not running", arrived as the
same four characters: 被拒绝.

That is not a missing message. It is a missing contract, and the cost is paid by
whoever is holding the phone: the one fact that would have ended the search —
*a credential is not configured on this Host* — existed at the bottom of the
call chain and was thrown away twice on the way up.

So: **one envelope, emitted by every surface, parsed by every client.**

What belongs here and what does not
-----------------------------------

Here: the vocabulary a *client* acts on, and the field names it reads.

Not here: which internal authority refused. "memory", "agent", "hub" are one
process's view of its own upstreams — useful in a log, meaningless to a phone,
and a topology no client should learn. A screen already knows its subject: it
asked for the memory library, so ``not_running`` is enough for it to say
"记忆还没启动". Naming the authority would tell it something true and useless,
and make the internal service graph part of a public contract.

Also not here: the mapping from a producer's internal failure taxonomy onto
:data:`REFUSAL_KINDS`. That projection is the producer's own judgement and
belongs at the boundary that publishes it — the layer whose whole job is not
handing a client its internals.

Non-Python clients keep language-native mirrors of this vocabulary. For the
Owner management surface those mirrors are *generated* from the OpenAPI artifact
that describes it, so they cannot drift by hand; a contract test on each side
proves the generated file still matches. A surface that is not described by that
artifact keeps a hand-written mirror and a test that compares it to this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Why the answer is no, in the terms that change what a client *does*.
#:
#: Coarse on purpose. A vocabulary a client cannot act on differently is a
#: vocabulary it will ignore, and every value here earns its place by leading
#: somewhere else: a different sentence to a person, a retry offered or withheld,
#: a re-read instead of a retry.
RefusalKind = Literal[
    #: You are not who this needs, or no longer are. The client's move is to
    #: authenticate again — once — not to retry the call.
    "denied",
    #: There is nothing here. Deliberately also the answer for "this exists but
    #: is not yours": an identifier must not be probeable for existence.
    "not_found",
    #: Somebody changed this first, or the domain will not allow it in this
    #: state. **The one refusal answered by re-reading rather than retrying** —
    #: a retried stale write means whichever client is more persistent wins,
    #: which is what neither person asked for.
    "conflict",
    #: The request itself was wrong. A client bug, and not something a person
    #: can be asked to fix by tapping again.
    "invalid",
    #: This Host was never set up for this. Retrying is pointless and so is
    #: waiting: nothing changes until somebody configures the Host. Its own kind
    #: rather than a flavour of ``not_running`` because it sends people to a
    #: different place — the installation, not the service.
    "not_configured",
    #: The part of this Host that answers this is not up. Waiting may be enough,
    #: so a retry is worth offering.
    "not_running",
    #: It answered, and the answer was a failure or outside its contract.
    #: Nothing the client did caused it and nothing it can do fixes it.
    "upstream",
]

REFUSAL_KINDS: tuple[str, ...] = (
    "denied",
    "not_found",
    "conflict",
    "invalid",
    "not_configured",
    "not_running",
    "upstream",
)

#: Declared next to the values so a mirror in another language can be checked
#: against it, and so the set cannot be extended in one of the two places.
REFUSAL_KIND_SET = frozenset(REFUSAL_KINDS)


class Refusal(BaseModel):
    """One refusal, in the only shape an Eidolon surface may publish.

    Carried under ``detail`` by HTTP surfaces, because that is where FastAPI's
    error body puts it and where every client already looks. The status code
    still says how to treat the response at the transport layer; this says what
    happened, and the two are different questions — which is why a status alone
    was never enough to draw a screen from.
    """

    model_config = ConfigDict(extra="forbid")

    kind: RefusalKind
    #: The producer's own sentence, for a person to read. Never parsed: matching
    #: on prose across a process boundary is not a contract, which is what
    #: ``kind`` and ``code`` are for.
    reason: str = Field(default="", max_length=512)
    #: The domain's word for *which* refusal this is, when there is one —
    #: ``revision_stale``, ``default_replacement_required``. Null is the normal
    #: case and means "no further detail", not a kind of failure.
    code: str | None = Field(default=None, max_length=64)
    #: Whether the same request, unchanged, could succeed later. Mostly implied
    #: by ``kind`` and carried anyway for the one case it is not: an upstream
    #: failure may or may not be worth waiting out, and only the producer knows.
    retryable: bool = False


def refusal_body(refusal: Refusal) -> dict:
    """The wire body for a refusal, ``detail`` wrapper included.

    A function rather than a convention at each raise site: the wrapper is part
    of the shape a client parses, and "some routes wrap it and some do not" is
    the same class of drift this module exists to end.
    """

    return {"detail": refusal.model_dump()}
