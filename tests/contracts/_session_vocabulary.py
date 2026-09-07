"""The session-control vocabulary a client mirror has to have decided about.

A roll-call of assertions cannot catch the constant that was just added, and on
2026-08-26 that cost twelve days: `SESSION_CONVERSATION_ID_FIELD` entered this
contract, the ESP32 mirror asserted it and went red the same day, the mobile
mirror listed neither it nor the schema version and stayed green. The phone
published a session request without the member that makes it a request; the
Provider drops such a packet rather than refusing it, so a pad sat in a room
with its microphone open and nobody asked to answer, with no log line on either
side.

So the unit here is the vocabulary, not the constant. Every name in it must
carry a decision — mirrored to a named client constant, or deliberately not
mirrored, with a reason. A name that lands in neither is the failure, and it is
named. The Mission Control mirrors in the same directory already work this way
against published sets; this derives the set from the contract instead, because
the session names are a family rather than an enum.
"""

from __future__ import annotations

from eidolon_sdk.biz import contracts as c

#: Prefixes that make a contract constant part of this vocabulary. `WIRE_` is
#: here because `WIRE_SCHEMA_VERSION` travels in the same envelope and was the
#: other name the mobile mirror had never asserted.
_PREFIXES = ("SESSION_", "WIRE_")


def names() -> set[str]:
    return {name for name in dir(c) if name.startswith(_PREFIXES)}


def assert_every_name_is_decided(
    *,
    client: str,
    mirrored: dict[str, str],
    unmirrored: dict[str, str],
) -> None:
    """Hold one client's mirror to the whole vocabulary.

    `mirrored` maps a contract name to the client constant that carries it;
    `unmirrored` maps a contract name to why this client does not.
    """

    vocabulary = names()
    decided = set(mirrored) | set(unmirrored)

    both = set(mirrored) & set(unmirrored)
    assert not both, f"{client}: {sorted(both)} are recorded as mirrored and as not mirrored"

    unknown = decided - vocabulary
    assert not unknown, (
        f"{client}: {sorted(unknown)} are not in this contract — a decision about a name that "
        "no longer exists outlives the thing it was about"
    )

    undecided = vocabulary - decided
    assert not undecided, (
        f"{client}: {sorted(undecided)} entered the session vocabulary and this mirror says "
        "nothing about them. Either assert the client constant that carries each one, or "
        "record why this client does not carry it. Silence is what let a phone publish a "
        "session request for twelve days that the Provider dropped without a word."
    )

    empty = sorted(name for name, reason in unmirrored.items() if not reason.strip())
    assert not empty, f"{client}: {empty} are excused without a reason"
