"""The one declaration of the global audit stream.

Every authority publishes governance facts into this stream and Admin projects
it into a query index, so its name, subjects and limits are a contract between
repositories — not a setting either end may hold privately. They were held
privately: the publisher knew only the subject prefix, the consumer knew the
name and the limits, and **the consumer was the only thing that created it**.

That made the transport of governance facts depend on one Owner-facing
component being up. A Host whose Admin was not running had no stream at all, so
every authority's dispatcher published into nothing, retried with backoff and
purged nothing. Nothing was lost — an unpublished row is still readable by its
Owner — but a dependency in that direction is backwards: Data and Agent do not
otherwise care whether anybody is looking at a panel.

Ensuring the stream is the publisher's job as much as the consumer's, which is
what the rest of this workspace already does — ``eidolon_agent``'s bus ensures
the streams it owns when it connects, and ``eidolon_memory`` ensures its own.
Whoever connects first creates it; everyone after finds it. Nothing waits for
anyone.

**Create, never update.** The limits below are what a fresh Host gets. An
existing stream is left exactly as it is, because an operator who widened a
retention window on a running Host should not have it silently narrowed back by
the next process to connect.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

#: Stream name. Versioned, because the envelope is: a breaking change to the
#: contract gets a new stream rather than a reinterpretation of this one.
AUDIT_STREAM_NAME = "EIDOLON_AUDIT_V1"

#: Subject root. Publishers append one token naming the producing authority, so
#: the stream binds ``<prefix>.>``.
AUDIT_SUBJECT_PREFIX = "eidolon.audit.v1"

#: How long the bus keeps a governance fact.
#:
#: This is the horizon of "rebuildable": dropping Admin's index and replaying
#: recovers a month, not a history. The history a person reads lives in each
#: authority's own table and is kept there on its own schedule — which is why
#: this can be a transport window rather than a retention promise.
AUDIT_MAX_AGE = timedelta(days=30)

#: And a size bound, so a misbehaving producer costs disk rather than a Host.
AUDIT_MAX_BYTES = 512 * 1024 * 1024


def audit_subject(producer: str) -> str:
    """The subject one authority publishes on, from its producer name."""

    normalized = "".join(
        char if char.isalnum() or char in "_-" else "_" for char in producer
    )
    return f"{AUDIT_SUBJECT_PREFIX}.{normalized or 'unknown'}"


async def ensure_audit_stream(jetstream: Any) -> None:
    """Create the audit stream if this Host has not got one yet.

    Idempotent and safe to race: two authorities connecting at once both see it
    missing, both create it, and the loser of that race gets the same stream it
    was going to get anyway.
    """

    from nats.js import api
    from nats.js.errors import BadRequestError, NotFoundError

    try:
        await jetstream.stream_info(AUDIT_STREAM_NAME)
        return
    except NotFoundError:
        pass
    try:
        await jetstream.add_stream(
            config=api.StreamConfig(
                name=AUDIT_STREAM_NAME,
                subjects=[f"{AUDIT_SUBJECT_PREFIX}.>"],
                retention=api.RetentionPolicy.LIMITS,
                storage=api.StorageType.FILE,
                max_age=AUDIT_MAX_AGE.total_seconds(),
                max_bytes=AUDIT_MAX_BYTES,
            )
        )
    except BadRequestError:
        # Someone else created it between the two calls above. That is the
        # outcome this function exists to produce.
        return


__all__ = [
    "AUDIT_MAX_AGE",
    "AUDIT_MAX_BYTES",
    "AUDIT_STREAM_NAME",
    "AUDIT_SUBJECT_PREFIX",
    "audit_subject",
    "ensure_audit_stream",
]
