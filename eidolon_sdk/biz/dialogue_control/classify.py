"""Deterministic interrupt/control-intent classification.

Pure functions over the shared lexicons — no runtime dependencies, safe for
both the channel Tier0 hot path (<1ms) and the agent reflex layer.
"""

from __future__ import annotations

from eidolon_sdk.biz.dialogue_control.intents import (
    InterruptIntent,
    InterruptIntentResult,
)
from eidolon_sdk.biz.dialogue_control.lexicon import (
    ASR_EXACT_CANONICALIZATIONS,
    ASR_PREFIX_CANONICALIZATIONS,
    BACKCHANNEL_WORDS,
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


def normalize_interrupt_text(text: str) -> str:
    return text.strip().lower().rstrip(INTERRUPT_TEXT_TRAILING_CHARS)


def canonicalize_interrupt_text(text: str) -> str:
    """Normalize common hot-path STT confusions without changing raw logs."""

    stripped = normalize_interrupt_text(text)
    if stripped in ASR_EXACT_CANONICALIZATIONS:
        return ASR_EXACT_CANONICALIZATIONS[stripped]
    for source_prefix, target_prefix in ASR_PREFIX_CANONICALIZATIONS:
        if stripped.startswith(source_prefix):
            return target_prefix + stripped[len(source_prefix) :]
    return stripped


_HARD_STOP_PREFIXES = tuple(
    normalize_interrupt_text(item) for item in DEFAULT_HARD_STOP_PREFIX_LEXICON
)
_HARD_STOPS = tuple(normalize_interrupt_text(item) for item in DEFAULT_HARD_STOP_LEXICON)
_HARD_STOP_NEGATION_PREFIXES = tuple(
    normalize_interrupt_text(item) for item in DEFAULT_HARD_STOP_NEGATION_PREFIXES
)
_HARD_STOP_SPEECH_VERBS = tuple(
    normalize_interrupt_text(item) for item in DEFAULT_HARD_STOP_SPEECH_VERBS
)
_HARD_STOP_CONTROL_SUFFIXES = tuple(
    normalize_interrupt_text(item) for item in DEFAULT_HARD_STOP_CONTROL_SUFFIXES
)
_TOPIC_SWITCH = tuple(
    normalize_interrupt_text(item) for item in DEFAULT_TOPIC_SWITCH_LEXICON
)
_CORRECTION = tuple(normalize_interrupt_text(item) for item in DEFAULT_CORRECTION_LEXICON)


def _count_cjk(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def hard_stop_prefix_intent(
    text: str,
    *,
    min_chars: int = 2,
    min_cjk_chars: int = 2,
) -> InterruptIntent | None:
    """Classify high-precision Tier0 hard-stop prefixes."""

    stripped = canonicalize_interrupt_text(text)
    if len(stripped) < min_chars or _count_cjk(stripped) < min_cjk_chars:
        return None
    if stripped in _HARD_STOP_PREFIXES or _hard_stop_speech_pattern(stripped):
        return InterruptIntent.HARD_STOP
    return None


def hard_stop_intent(text: str) -> InterruptIntent | None:
    """Classify only Tier0 hard-stop text.

    Non-Tier0 interruption semantics intentionally do not live in lexical
    hot-path rules. They should come from transcript evidence, EOT/turn
    detection, or a future validated lightweight model.
    """

    stripped = canonicalize_interrupt_text(text)
    if not stripped:
        return None
    if any(candidate and candidate in stripped for candidate in _HARD_STOPS):
        return InterruptIntent.HARD_STOP
    if _hard_stop_speech_pattern(stripped):
        return InterruptIntent.HARD_STOP
    return hard_stop_prefix_intent(stripped)


def _hard_stop_speech_pattern(
    text: str,
    *,
    require_control_suffix: bool = False,
) -> bool:
    """Match high-precision Chinese "stop talking" commands.

    This covers the productive Tier0 family ("不要讲了", "先别继续说了")
    without treating ordinary questions such as "不要讲英文怎么说" as stops.
    """

    stripped = canonicalize_interrupt_text(text)
    if not stripped:
        return False
    for prefix in _HARD_STOP_NEGATION_PREFIXES:
        if not prefix or not stripped.startswith(prefix):
            continue
        after_prefix = stripped[len(prefix) :]
        for verb in _HARD_STOP_SPEECH_VERBS:
            if not verb or not after_prefix.startswith(verb):
                continue
            suffix = after_prefix[len(verb) :]
            if suffix in _HARD_STOP_CONTROL_SUFFIXES and (
                suffix or not require_control_suffix
            ):
                return True
    return False


# Clause punctuation only — never whitespace, which would shred English
# stop phrases like "stop talking".
_CLAUSE_SEPARATORS = "，,。.；;！!？?、"


def _split_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch in _CLAUSE_SEPARATORS:
            if current:
                clauses.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        clauses.append("".join(current))
    return clauses


def _clause_is_hard_stop(clause: str) -> bool:
    if clause in _HARD_STOPS or _hard_stop_speech_pattern(clause):
        return True
    for candidate in _HARD_STOPS:
        if not candidate or not clause.startswith(candidate):
            continue
        if clause[len(candidate) :] in _HARD_STOP_CONTROL_SUFFIXES:
            return True
    return False


def classify_control_intent(text: str) -> InterruptIntentResult:
    """Classify a full utterance for the agent-side reflex layer.

    Unlike the channel Tier0 path (which sees partial ASR interim results and
    must never over-fire), the agent sees the final utterance of a started
    turn. Precedence: hard stop > exact backchannel/noise > topic switch >
    correction > uncertain. A hard stop only counts when the whole utterance
    is a control command — "停一下再帮我查天气" carries new content and must
    NOT short-circuit the turn, so containment checks are anchored to the
    canonicalized full text being (nearly) consumed by the control phrase.
    """

    stripped = canonicalize_interrupt_text(text)
    if not stripped:
        return InterruptIntentResult(InterruptIntent.NOISE, 1.0, "lexicon", "empty_text")

    if stripped in BACKCHANNEL_WORDS:
        return InterruptIntentResult(
            InterruptIntent.BACKCHANNEL, 0.95, "lexicon", "backchannel"
        )
    if stripped in NOISE_LIKE_TRANSCRIPTIONS or (
        2 <= len(stripped) <= 6
        and len(set(stripped)) == 1
        and stripped[0] in REPEATED_NOISE_CHARS
    ):
        return InterruptIntentResult(InterruptIntent.NOISE, 0.9, "lexicon", "noise_like")

    # Whole-utterance stop: the text must BE a stop command, not merely
    # contain one. "停，别说了" is two stop clauses and counts; "停一下再帮我
    # 查天气" carries new content and must not. Split on clause punctuation
    # and require every clause to be stop-shaped.
    clauses = [c for c in _split_clauses(stripped) if c]
    if clauses and all(_clause_is_hard_stop(c) for c in clauses):
        return InterruptIntentResult(
            InterruptIntent.HARD_STOP,
            1.0 if len(clauses) == 1 else 0.98,
            "lexicon",
            "hard_stop_whole_utterance",
        )

    if any(c and c in stripped for c in _TOPIC_SWITCH):
        return InterruptIntentResult(
            InterruptIntent.TOPIC_SWITCH, 0.95, "lexicon", "topic_switch"
        )
    if any(c and stripped.startswith(c) for c in _CORRECTION):
        return InterruptIntentResult(
            InterruptIntent.CORRECTION, 0.85, "lexicon", "correction"
        )
    return InterruptIntentResult(InterruptIntent.UNCERTAIN, 0.0, "lexicon", "no_match")


class LexiconInterruptClassifier:
    """Low-latency classifier for Tier0 plus non-lexical noise shape.

    Topic switch, correction, and backchannel word lists are deliberately not
    used on the channel hot path unless ``fast_intents`` is enabled. Outside
    Tier0, hot-path intent should be decided by EOT/semantic evidence or a
    separately validated model.
    """

    def __init__(
        self,
        *,
        fast_intents: bool = False,
        repeated_noise_min_chars: int = 2,
        repeated_noise_max_chars: int = 6,
    ) -> None:
        self._fast_intents = fast_intents
        self._repeated_noise_min_chars = max(1, int(repeated_noise_min_chars))
        self._repeated_noise_max_chars = max(
            self._repeated_noise_min_chars,
            int(repeated_noise_max_chars),
        )

    def classify(
        self,
        text: str,
        *,
        vad_active: bool,
        agent_speaking: bool,
        eot_score: float,
    ) -> InterruptIntentResult:
        stripped = canonicalize_interrupt_text(text)
        if not stripped:
            return InterruptIntentResult(
                InterruptIntent.NOISE, 1.0, "lexicon", "empty_transcript"
            )

        if any(c and c in stripped for c in _HARD_STOPS):
            return InterruptIntentResult(
                InterruptIntent.HARD_STOP, 1.0, "lexicon", "hard_stop"
            )
        if _hard_stop_speech_pattern(stripped, require_control_suffix=True):
            return InterruptIntentResult(
                InterruptIntent.HARD_STOP,
                0.98,
                "lexicon_pattern",
                "hard_stop_speech_control",
            )
        if stripped in BACKCHANNEL_WORDS:
            return InterruptIntentResult(
                InterruptIntent.BACKCHANNEL, 0.95, "lexicon", "backchannel"
            )
        if stripped in NOISE_LIKE_TRANSCRIPTIONS:
            return InterruptIntentResult(
                InterruptIntent.NOISE, 0.90, "lexicon", "noise_like"
            )
        if self._fast_intents and any(c and c in stripped for c in _TOPIC_SWITCH):
            return InterruptIntentResult(
                InterruptIntent.TOPIC_SWITCH, 0.95, "lexicon", "topic_switch"
            )
        if self._fast_intents and any(c and c in stripped for c in _CORRECTION):
            return InterruptIntentResult(
                InterruptIntent.CORRECTION, 0.85, "lexicon", "correction"
            )
        if (
            self._repeated_noise_min_chars
            <= len(stripped)
            <= self._repeated_noise_max_chars
            and len(set(stripped)) == 1
            and stripped[0] in REPEATED_NOISE_CHARS
        ):
            return InterruptIntentResult(
                InterruptIntent.NOISE, 0.85, "lexicon", "repeated_noise_char"
            )
        return InterruptIntentResult(
            InterruptIntent.UNCERTAIN, 0.0, "lexicon", "no_lexical_match"
        )
