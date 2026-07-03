"""Interrupt/control intent taxonomy shared by channel and agent."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InterruptIntent(str, Enum):
    HARD_STOP = "hard_stop"
    TOPIC_SWITCH = "topic_switch"
    CORRECTION = "correction"
    BACKCHANNEL = "backchannel"
    NOISE = "noise"
    NORMAL_INTERRUPT = "normal_interrupt"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class InterruptIntentResult:
    intent: InterruptIntent
    confidence: float
    source: str
    reason: str = ""
