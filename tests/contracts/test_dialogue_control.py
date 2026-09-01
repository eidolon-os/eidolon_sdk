"""Contract tests for the shared dialogue-control taxonomy and lexicons.

These pin the behaviour both eidolon_channel (Tier0 fast path) and
eidolon_agent (reflex layer) rely on. If a case here changes, both consumers
change together — that is the point of the shared module.
"""

from __future__ import annotations

import pytest

from eidolon_sdk.biz.dialogue_control import (
    InterruptIntent,
    LexiconInterruptClassifier,
    canonicalize_interrupt_text,
    classify_control_intent,
    hard_stop_intent,
)


class TestHardStopIntent:
    @pytest.mark.parametrize(
        "text",
        [
            "停，别说了",
            "停一下",
            "别说了",
            "先别讲了",
            "不要再说了",
            "闭嘴",
            "stop talking",
            "先别继续说了",
            "不要讲了",
        ],
    )
    def test_stop_commands_classify_as_hard_stop(self, text: str) -> None:
        assert hard_stop_intent(text) is InterruptIntent.HARD_STOP

    @pytest.mark.parametrize(
        "text",
        [
            "不要讲英文怎么说",
            "今天天气怎么样",
            "",
        ],
    )
    def test_ordinary_text_is_not_hard_stop(self, text: str) -> None:
        assert hard_stop_intent(text) is not InterruptIntent.HARD_STOP

    def test_asr_homophone_canonicalization(self) -> None:
        assert canonicalize_interrupt_text("亭") == "停"

class TestClassifyControlIntent:
    def test_whole_utterance_stop(self) -> None:
        result = classify_control_intent("停，别说了")
        assert result.intent is InterruptIntent.HARD_STOP
        assert result.confidence >= 0.9

    def test_stop_with_polite_tail(self) -> None:
        assert (
            classify_control_intent("停一下吧").intent is InterruptIntent.HARD_STOP
        )

    def test_stop_plus_new_content_is_not_stop(self) -> None:
        # Carries a new task — must not short-circuit the turn.
        result = classify_control_intent("停一下再帮我查天气")
        assert result.intent is not InterruptIntent.HARD_STOP

    def test_topic_switch(self) -> None:
        assert (
            classify_control_intent("我们换个话题吧").intent
            is InterruptIntent.TOPIC_SWITCH
        )

    def test_correction(self) -> None:
        assert (
            classify_control_intent("不是这个意思，我是说明天").intent
            is InterruptIntent.CORRECTION
        )

    def test_backchannel(self) -> None:
        assert classify_control_intent("嗯嗯").intent is InterruptIntent.BACKCHANNEL

    def test_noise(self) -> None:
        assert classify_control_intent("啊啊啊").intent is InterruptIntent.NOISE

    def test_normal_query_is_uncertain(self) -> None:
        assert (
            classify_control_intent("帮我查一下明天的天气").intent
            is InterruptIntent.UNCERTAIN
        )


class TestLexiconInterruptClassifier:
    def test_hard_stop_on_hot_path(self) -> None:
        clf = LexiconInterruptClassifier()
        result = clf.classify(
            "别说了", vad_active=True, agent_speaking=True, eot_score=0.5
        )
        assert result.intent is InterruptIntent.HARD_STOP

    def test_backchannel_does_not_steal_turn(self) -> None:
        clf = LexiconInterruptClassifier()
        result = clf.classify(
            "嗯嗯", vad_active=True, agent_speaking=True, eot_score=0.1
        )
        assert result.intent is InterruptIntent.BACKCHANNEL

    def test_topic_switch_requires_fast_intents(self) -> None:
        conservative = LexiconInterruptClassifier()
        fast = LexiconInterruptClassifier(fast_intents=True)
        text = "我们换个话题"
        kw = dict(vad_active=True, agent_speaking=True, eot_score=0.5)
        assert conservative.classify(text, **kw).intent is InterruptIntent.UNCERTAIN
        assert fast.classify(text, **kw).intent is InterruptIntent.TOPIC_SWITCH

    def test_repeated_noise_char(self) -> None:
        clf = LexiconInterruptClassifier()
        result = clf.classify(
            "咳咳咳", vad_active=True, agent_speaking=False, eot_score=0.0
        )
        assert result.intent is InterruptIntent.NOISE
