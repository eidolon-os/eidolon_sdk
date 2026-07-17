"""Versioned sense.* perception-plane contracts (desktop co-presence)."""

from .protocol import (
    SENSE_ATTENTION_TYPE,
    SENSE_EVENT_TYPE,
    SENSE_FATIGUE_TYPE,
    SENSE_SCHEMA_VERSION,
    SENSE_SESSION_TYPE,
    SenseAttention,
    SenseEvent,
    SenseFatigue,
    SenseMessage,
    SenseSession,
    parse_sense_message,
)

__all__ = [
    "SENSE_SCHEMA_VERSION",
    "SENSE_ATTENTION_TYPE",
    "SENSE_SESSION_TYPE",
    "SENSE_FATIGUE_TYPE",
    "SENSE_EVENT_TYPE",
    "SenseAttention",
    "SenseSession",
    "SenseFatigue",
    "SenseEvent",
    "SenseMessage",
    "parse_sense_message",
]
