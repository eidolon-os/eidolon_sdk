"""Shared dialogue-control contracts: intent hints and committed decisions.

Single source of truth for provider-neutral dialogue contracts:

- eidolon_channel collects provider-neutral evidence while deciding a turn;
- the channel's product commit boundary emits ``CommittedTurnDecision``;
- eidolon_agent validates that typed commitment and handles the text normally.

The commitment carries no lexical intent, keeping fixed phrases out of
cross-process authority. Legacy lexicon exports remain for offline evaluation
and compatibility; production turn commitment does not execute them.
"""

from eidolon_sdk.biz.dialogue_control.classify import (
    LexiconInterruptClassifier,
    canonicalize_interrupt_text,
    classify_control_intent,
    hard_stop_intent,
    hard_stop_prefix_intent,
    normalize_interrupt_text,
)
from eidolon_sdk.biz.dialogue_control.intents import (
    InterruptIntent,
    InterruptIntentResult,
)
from eidolon_sdk.biz.dialogue_control.lexicon import (
    ASR_EXACT_CANONICALIZATIONS,
    ASR_PREFIX_CANONICALIZATIONS,
    BACKCHANNEL_WORDS,
    DEFAULT_ATTENTION_EARLY_DUCK_PREFIX_LEXICON,
    DEFAULT_CORRECTION_EXCLUSION_LEXICON,
    DEFAULT_CORRECTION_LEXICON,
    DEFAULT_HARD_STOP_CONTROL_SUFFIXES,
    DEFAULT_HARD_STOP_LEXICON,
    DEFAULT_HARD_STOP_NEGATION_PREFIXES,
    DEFAULT_HARD_STOP_PREFIX_LEXICON,
    DEFAULT_HARD_STOP_SPEECH_VERBS,
    DEFAULT_TOPIC_SWITCH_LEXICON,
    INTERRUPT_TEXT_TRAILING_CHARS,
    NOISE_LIKE_TRANSCRIPTIONS,
    REPEATED_NOISE_CHARS,
)
from eidolon_sdk.biz.dialogue_control.turn_decision import (
    TURN_DECISION_SCHEMA_VERSION,
    CommittedTurnDecision,
    CommittedTurnEvidence,
    TurnCommitBoundary,
    committed_turn_text_sha256,
)

__all__ = [
    "ASR_EXACT_CANONICALIZATIONS",
    "ASR_PREFIX_CANONICALIZATIONS",
    "BACKCHANNEL_WORDS",
    "CommittedTurnDecision",
    "CommittedTurnEvidence",
    "DEFAULT_ATTENTION_EARLY_DUCK_PREFIX_LEXICON",
    "DEFAULT_CORRECTION_EXCLUSION_LEXICON",
    "DEFAULT_CORRECTION_LEXICON",
    "DEFAULT_HARD_STOP_CONTROL_SUFFIXES",
    "DEFAULT_HARD_STOP_LEXICON",
    "DEFAULT_HARD_STOP_NEGATION_PREFIXES",
    "DEFAULT_HARD_STOP_PREFIX_LEXICON",
    "DEFAULT_HARD_STOP_SPEECH_VERBS",
    "DEFAULT_TOPIC_SWITCH_LEXICON",
    "INTERRUPT_TEXT_TRAILING_CHARS",
    "InterruptIntent",
    "InterruptIntentResult",
    "LexiconInterruptClassifier",
    "NOISE_LIKE_TRANSCRIPTIONS",
    "REPEATED_NOISE_CHARS",
    "TURN_DECISION_SCHEMA_VERSION",
    "TurnCommitBoundary",
    "canonicalize_interrupt_text",
    "classify_control_intent",
    "committed_turn_text_sha256",
    "hard_stop_intent",
    "hard_stop_prefix_intent",
    "normalize_interrupt_text",
]
