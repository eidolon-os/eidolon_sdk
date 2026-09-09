"""What a spoken turn is allowed to cost, stated once.

A turn crosses three services and two repositories, and every hop had its own
timeout: recognition 5 s to connect and 15 s for a final, the Agent 10 s, the
voice 15 s for a first frame and 30 s for a first token. Five numbers chosen
independently, and nothing anywhere that said what they should add up to. They
add up to a minute.

The one that actually fired was not chosen at all. `grpc_llm` reads the first
text chunk under `APIConnectOptions.timeout`, whose framework default is 10 s —
a *connection* timeout standing in for a *first-delta* deadline. Against a
hosted model the two are nearly the same thing, so it never mattered; against a
model on this Host's own little cores they are not, and a turn that needed 11 s
of prompt reading was cancelled at 10 with `Cannot write to closing transport`
and no text to speak. The number was never wrong. It was never anyone's.

So the budget is declared here, and each hop's allowance is derived from it.
What that buys is not speed — it is that a combination which cannot fit becomes
visible where it is decided rather than in front of a microphone. With the
allowances below, a Host whose model needs 11 s to read a prompt fails the
`test_the_allowances_fit_the_budget` arithmetic, not a user's evening.

Measured on RK3588 (release rk3588-20260909T123444), speech stop to first
audio, so that the numbers below are answerable rather than aspirational:

    recognition final          2.0 - 2.6 s
    first text token           0.85 s with a warm prefix, 13 s cold
    voice first audio          2.2 s steady, 3.0 s after a restart

The floor is therefore about 5 s today with a warm prefix, and the product
wants far less. That gap is the roadmap, not a reason to leave the budget
unstated: an undeclared budget cannot be missed, and this one has been missed
for as long as it has existed.
"""

from __future__ import annotations

from typing import Final

#: Speech stop to first audible word. The number a listener experiences, and
#: the only one a product requirement can be written against.
#:
#: 6 s rather than the 2 s a companion wants, because a budget nobody can meet
#: is a budget everybody routes around — and the measured floor above is 5 s.
#: Lower it when a hop gets faster; every allowance below follows.
TURN_FIRST_AUDIO_BUDGET_S: Final = 6.0

#: How the budget divides. Fractions rather than seconds so that changing the
#: budget moves every hop, which is the whole point of deriving them.
#:
#: The split is what the hops measured above actually need, not an even
#: division: recognition and voice are bounded by model work that is already
#: understood, and the middle hop gets what is left.
RECOGNITION_SHARE: Final = 0.45
GENERATION_SHARE: Final = 0.20
VOICE_SHARE: Final = 0.35


def recognition_allowance_s(budget_s: float = TURN_FIRST_AUDIO_BUDGET_S) -> float:
    """Speech stop to a final transcript."""

    return round(budget_s * RECOGNITION_SHARE, 3)


def generation_allowance_s(budget_s: float = TURN_FIRST_AUDIO_BUDGET_S) -> float:
    """Transcript accepted to the first text chunk.

    This is the one the framework was answering with a connection default. It
    covers prompt assembly *and* the model reading the prompt, so a Host whose
    prefix cache is cold, or whose prompt puts volatile content ahead of
    reusable content, spends it before saying a word.
    """

    return round(budget_s * GENERATION_SHARE, 3)


def voice_allowance_s(budget_s: float = TURN_FIRST_AUDIO_BUDGET_S) -> float:
    """First text chunk to the first audio frame."""

    return round(budget_s * VOICE_SHARE, 3)


#: What a hop may wait before it gives up, as opposed to what it is expected to
#: take. A hop that waits its own allowance and no longer fails fast enough to
#: leave the turn recoverable; one that waits many times it hides the miss.
#: Twice, so a hop that is merely slow is reported as slow rather than as
#: broken, and a hop that is broken does not eat another hop's allowance.
GIVE_UP_MULTIPLIER: Final = 2.0


def give_up_after_s(allowance_s: float) -> float:
    """The timeout a hop should carry, derived from what it is allowed to take."""

    return round(allowance_s * GIVE_UP_MULTIPLIER, 3)
