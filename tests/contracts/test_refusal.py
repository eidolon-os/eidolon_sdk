"""The refusal envelope is a contract, so its shape is asserted, not assumed.

Two things are worth failing over here. One is the vocabulary being extended in
one of its two spellings — the ``Literal`` and the tuple — because a value the
model accepts and the mirror-checkable tuple does not is exactly how a client in
another language ends up unable to parse a refusal it is sent. The other is a
field quietly changing name or default, because every consumer of this envelope
reads it positionally by key and none of them can see this file.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.contracts.refusal import (
    REFUSAL_KIND_SET,
    REFUSAL_KINDS,
    Refusal,
    RefusalKind,
    refusal_body,
)


def test_the_vocabulary_is_spelled_once() -> None:
    """The type and the checkable tuple are the same set, in the same order.

    Order too: the tuple is what a mirror in another language is compared
    against, and a reviewer reading two lists in different orders cannot see at
    a glance that they agree.
    """

    assert get_args(RefusalKind) == REFUSAL_KINDS
    assert REFUSAL_KIND_SET == set(REFUSAL_KINDS)


@pytest.mark.parametrize("kind", REFUSAL_KINDS)
def test_every_declared_kind_is_a_refusal_the_model_accepts(kind: str) -> None:
    """No kind may exist that cannot be put on a wire.

    The failure this guards against is not hypothetical: the taxonomy this
    envelope replaces had an authority value the raising code used and the
    serialising model rejected, so an entire family of refusals died inside the
    error path and surfaced as an unexplained 500.
    """

    refusal = Refusal(kind=kind, reason="because", retryable=False)
    assert refusal.kind == kind
    assert refusal_body(refusal) == {
        "detail": {
            "kind": kind,
            "reason": "because",
            "code": None,
            "retryable": False,
        }
    }


def test_a_refusal_needs_nothing_but_its_kind() -> None:
    """Every other field is optional, because a producer may know nothing else.

    A required ``reason`` would push producers into writing filler prose, and
    filler is worse than absence: a client cannot tell it from a real sentence.
    """

    refusal = Refusal(kind="not_running")
    assert refusal.reason == ""
    assert refusal.code is None
    assert refusal.retryable is False


def test_an_unknown_kind_is_refused_rather_than_relayed() -> None:
    assert REFUSAL_KIND_SET.isdisjoint({"unavailable", "configuration", ""})
    with pytest.raises(ValidationError):
        Refusal(kind="unavailable")


def test_nothing_extra_rides_along() -> None:
    """``extra="forbid"`` on purpose.

    A field that reaches a client without being in this file is a field no
    mirror has, no test covers, and some screen will come to depend on.
    """

    with pytest.raises(ValidationError):
        Refusal(kind="denied", authority="memory")
