"""Provider-neutral dialogue-control contracts.

Single source of truth for provider-neutral dialogue contracts:

- eidolon_channel collects provider-neutral evidence while deciding a turn;
- the channel's product commit boundary emits ``CommittedTurnDecision``;
- eidolon_agent validates that typed commitment and handles the text normally.

The commitment carries no lexical intent, keeping fixed phrases out of
cross-process authority. Intent values are model output labels only; this
package deliberately contains no phrase classifier or language-specific
word list.
"""
from eidolon_sdk.biz.dialogue_control.intents import (
    InterruptIntent,
    InterruptIntentResult,
)
from eidolon_sdk.biz.dialogue_control.turn_decision import (
    TURN_DECISION_SCHEMA_VERSION,
    CommittedTurnDecision,
    CommittedTurnEvidence,
    TurnCommitBoundary,
    committed_turn_text_sha256,
)

__all__ = [
    "CommittedTurnDecision",
    "CommittedTurnEvidence",
    "InterruptIntent",
    "InterruptIntentResult",
    "TURN_DECISION_SCHEMA_VERSION",
    "TurnCommitBoundary",
    "committed_turn_text_sha256",
]
