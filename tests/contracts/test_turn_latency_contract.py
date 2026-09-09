"""The turn budget, and the arithmetic that makes it mean something.

A budget nobody adds up is decoration. These tests are the addition.
"""

from __future__ import annotations

import pytest

from eidolon_sdk.biz.contracts import turn_latency as budget


def test_the_allowances_fit_the_budget() -> None:
    """The check the system did not have.

    Five timeouts were chosen independently and summed to about a minute, with
    nothing anywhere stating what a turn was allowed to cost. This is that
    statement, and it is arithmetic rather than prose so it can fail.
    """

    total = (
        budget.recognition_allowance_s()
        + budget.generation_allowance_s()
        + budget.voice_allowance_s()
    )

    assert total == pytest.approx(budget.TURN_FIRST_AUDIO_BUDGET_S, abs=0.01)
    assert (
        budget.RECOGNITION_SHARE + budget.GENERATION_SHARE + budget.VOICE_SHARE
        == pytest.approx(1.0)
    )


def test_every_allowance_moves_with_the_budget() -> None:
    """Derived, not chosen. Lowering the budget has to lower every hop, or the
    hops go back to being five independent numbers."""

    tighter = budget.TURN_FIRST_AUDIO_BUDGET_S / 2
    for allowance in (
        budget.recognition_allowance_s,
        budget.generation_allowance_s,
        budget.voice_allowance_s,
    ):
        assert allowance(tighter) < allowance(), allowance.__name__


def test_giving_up_takes_longer_than_the_allowance_but_not_much() -> None:
    """A hop that gives up at exactly its allowance reports every slow turn as
    a broken one; one that waits many times it hides the miss and eats the
    other hops' share."""

    allowance = budget.generation_allowance_s()

    assert budget.give_up_after_s(allowance) > allowance
    assert budget.give_up_after_s(allowance) < budget.TURN_FIRST_AUDIO_BUDGET_S


def test_the_budget_is_answerable_on_the_hardware_it_was_written_for() -> None:
    """Measured on RK3588, so the numbers are a requirement rather than a wish.

    A warm prefix produced a first text token in 0.85 s and a cold one in 13 s.
    The generation allowance sits between them on purpose: it declares that the
    prefix has to be warm, and it fails a Host where it is not — which is the
    property the previous 10-second framework default did not have.
    """

    warm_first_token_s = 0.85
    cold_first_token_s = 13.0

    assert warm_first_token_s < budget.generation_allowance_s()
    assert cold_first_token_s > budget.give_up_after_s(budget.generation_allowance_s())


def test_this_module_can_never_introduce_an_import_cycle() -> None:
    """Pure constants and arithmetic, like the contracts beside it."""

    from pathlib import Path

    source = Path(budget.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith(("import ", "from ")):
            assert "eidolon_sdk" not in line, line
