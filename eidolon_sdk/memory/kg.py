"""Memory command payload contracts for JetStream writes."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ._model import EidolonWireModel

KgPredicate = Literal[
    "child_of",
    "parent_of",
    "partner_of",
    "sibling_of",
    "friend_of",
    "colleague_of",
    "works_at",
    "lives_in",
    "studies_at",
    "holds_role",
    "born_in",
    "likes",
    "dislikes",
    "prefers",
    "does",
    "practices",
    "owns",
    "uses",
    "promised",
    "committed_to",
    "planned_to",
    "has_state",
    "has_emotion",
    "has_concern",
    "worried_about",
    "struggles_with",
    "has_health_condition",
    "takes_medication",
    "has_symptom",
    "attended",
    "experienced",
    "achieved",
]

SENSITIVE_PREDICATES: frozenset[str] = frozenset(
    {"has_health_condition", "takes_medication", "has_symptom"}
)

KG_PREDICATE_VALUES: tuple[str, ...] = tuple(
    getattr(KgPredicate, "__args__", ())  # type: ignore[attr-defined]
)


class _BaseMemoryCommand(EidolonWireModel):
    """Common fields on every command published to ``agent.memory.cmd.<user>``."""

    request_id: str
    user_id: str
    issued_at: str
    issuer: Literal["admin", "agent"] = "admin"


class KgAddTripleCommand(_BaseMemoryCommand):
    kind: Literal["kg_add_triple"] = "kg_add_triple"
    subject: str
    predicate: KgPredicate
    object: str
    valid_from: str | None = None
    valid_to: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source_drawer_id: str | None = None
    adapter_name: str = "admin"


class KgInvalidateCommand(_BaseMemoryCommand):
    kind: Literal["kg_invalidate"] = "kg_invalidate"
    subject: str
    predicate: KgPredicate
    object: str
    ended: str | None = None


class ConsolidatorIngestThemeCommand(_BaseMemoryCommand):
    kind: Literal["consolidator_ingest_theme"] = "consolidator_ingest_theme"
    text: str = Field(min_length=1)
    underlying_wing: str
    window_days: int = Field(gt=0, default=30)
    source_drawer_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)


class UserConfirmedFactCommand(_BaseMemoryCommand):
    kind: Literal["user_confirm_fact"] = "user_confirm_fact"
    text: str = Field(min_length=1)
    wing: str
    memory_type: str = "profile"
    importance: int = Field(ge=1, le=5, default=5)
    confidence: float = Field(ge=0.0, le=1.0, default=0.99)
    tags: list[str] = Field(default_factory=list)


USER_CONFIRMED_ROOM_PREFIX = "userconfirm:"

MemoryCommandPayload = (
    KgAddTripleCommand
    | KgInvalidateCommand
    | ConsolidatorIngestThemeCommand
    | UserConfirmedFactCommand
)
"""Discriminated union; route on the ``kind`` field."""
