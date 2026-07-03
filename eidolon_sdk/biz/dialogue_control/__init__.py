"""Shared dialogue-control contracts: interrupt/stop/topic-switch intents.

Single source of truth for the intent taxonomy and the deterministic hot-path
lexicons used on both sides of the Chat stream:

- eidolon_channel classifies barge-in transcripts on its fast path (Tier0) and
  cancels the in-flight turn;
- eidolon_agent re-classifies the query text on its slow path and returns the
  structured control intent (``termination_cause`` / ``control_intent``) so the
  upstream can circuit-break TTS and rendering.

Keeping both consumers on one lexicon prevents the two sides from drifting
apart on what counts as "停，别说了".
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

__all__ = [
    "ASR_EXACT_CANONICALIZATIONS",
    "ASR_PREFIX_CANONICALIZATIONS",
    "BACKCHANNEL_WORDS",
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
    "canonicalize_interrupt_text",
    "classify_control_intent",
    "hard_stop_intent",
    "hard_stop_prefix_intent",
    "normalize_interrupt_text",
]
