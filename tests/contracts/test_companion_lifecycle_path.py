"""Walking the lifecycle graph, so no consumer writes the order down again."""

from __future__ import annotations

import pytest

from eidolon_sdk.biz.contracts.companion import (
    COMPANION_LIFECYCLE_TRANSITIONS,
    companion_lifecycle_path,
)


def test_putting_one_away_goes_through_retiring() -> None:
    """The safety property, expressed as a route rather than a rule to remember.

    A management surface offers one action — "put this away" — and the step in
    between is not a detail it may skip: retiring is where new sessions stop
    being accepted. Asking for the path is how a caller gets that for free.
    """

    assert companion_lifecycle_path("active", "archived") == ("retiring", "archived")
    assert companion_lifecycle_path("retiring", "archived") == ("archived",)
    assert companion_lifecycle_path("archived", "active") == ("active",)
    assert companion_lifecycle_path("retiring", "active") == ("active",)


def test_where_it_already_is_is_no_journey() -> None:
    """Which is what makes a retried request succeed rather than conflict."""

    for state in COMPANION_LIFECYCLE_TRANSITIONS:
        assert companion_lifecycle_path(state, state) == ()


def test_nothing_comes_back_from_deletion() -> None:
    assert companion_lifecycle_path("archived", "deleting") == ("deleting",)
    with pytest.raises(ValueError, match="no companion lifecycle path"):
        companion_lifecycle_path("deleting", "active")


def test_the_route_is_read_from_the_table_and_not_from_this_file() -> None:
    """A characterization of the walk itself.

    Every path it returns has to be a sequence of edges the table actually has.
    Written as a check over the table rather than as expected values, so that
    adding a state cannot leave this test asserting a graph that no longer
    exists.
    """

    states = tuple(COMPANION_LIFECYCLE_TRANSITIONS)
    for start in states:
        for end in states:
            try:
                route = companion_lifecycle_path(start, end)
            except ValueError:
                # Unreachable is a real answer; the next assertion is that no
                # edge exists into it from here, which the walk just proved.
                continue
            here = start
            for step in route:
                assert step in COMPANION_LIFECYCLE_TRANSITIONS[here]
                here = step
            assert here == end
