"""Provider-neutral contract for a committed user-turn decision.

The contract deliberately carries no lexical intent. A consumer must never
promote a raw transcript or a fixed phrase match into a control action on its
own; this object only proves that a provider-neutral product boundary committed
the exact transcript.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

TURN_DECISION_SCHEMA_VERSION = 1


class TurnCommitBoundary(str, Enum):
    """Product boundary that made the transcript an irreversible user turn."""

    FRAMEWORK_COMPLETED = "framework_completed_turn"
    PTT_SEGMENT = "ptt_segment_commit"


def committed_turn_text_sha256(text: str) -> str:
    """Bind metadata to the exact trimmed transcript sent to the brain."""

    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CommittedTurnEvidence:
    """Provider-neutral evidence owned by a real product commit boundary."""

    boundary: TurnCommitBoundary
    transcript_final: bool
    vad_terminal: bool
    transcript_sha256: str
    eot_score: float | None = None

    def as_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "boundary": self.boundary.value,
            "transcript_final": self.transcript_final,
            "vad_terminal": self.vad_terminal,
            "transcript_sha256": self.transcript_sha256,
        }
        if self.eot_score is not None:
            metadata["eot_score"] = self.eot_score
        return metadata


@dataclass(frozen=True, slots=True)
class CommittedTurnDecision:
    """Typed transcript commitment emitted by a product turn boundary."""

    evidence: CommittedTurnEvidence
    schema_version: int = TURN_DECISION_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        text: str,
        boundary: TurnCommitBoundary,
        eot_score: float | None = None,
    ) -> "CommittedTurnDecision":
        """Create a transcript-bound record from authoritative commit evidence."""

        normalized_score = _optional_score(eot_score)
        return cls(
            evidence=CommittedTurnEvidence(
                boundary=boundary,
                transcript_final=True,
                vad_terminal=True,
                transcript_sha256=committed_turn_text_sha256(text),
                eot_score=normalized_score,
            ),
        )

    @classmethod
    def from_metadata(cls, value: object) -> "CommittedTurnDecision":
        """Strictly parse untrusted cross-process metadata.

        Raises ``ValueError`` for missing, malformed or unsupported fields so a
        caller can ignore the metadata without reclassifying raw text.
        """

        root = _mapping(value, field="turn_decision")
        version = root.get("schema_version")
        if isinstance(version, bool) or version != TURN_DECISION_SCHEMA_VERSION:
            raise ValueError(f"unsupported turn decision schema: {version!r}")
        if root.get("decision") != "commit":
            raise ValueError("turn decision must be a committed decision")
        evidence_raw = _mapping(root.get("evidence"), field="evidence")
        transcript_final = evidence_raw.get("transcript_final")
        vad_terminal = evidence_raw.get("vad_terminal")
        if transcript_final is not True or vad_terminal is not True:
            raise ValueError("committed turn evidence must be final and VAD-terminal")
        digest = _nonempty_string(
            evidence_raw.get("transcript_sha256"),
            field="transcript_sha256",
        )
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("transcript_sha256 must be lowercase SHA-256 hex")
        try:
            boundary = TurnCommitBoundary(
                _nonempty_string(evidence_raw.get("boundary"), field="boundary")
            )
        except ValueError as exc:
            raise ValueError(f"invalid turn decision enum: {exc}") from exc
        eot_score = _optional_score(evidence_raw.get("eot_score"))
        return cls(
            schema_version=TURN_DECISION_SCHEMA_VERSION,
            evidence=CommittedTurnEvidence(
                boundary=boundary,
                transcript_final=True,
                vad_terminal=True,
                transcript_sha256=digest,
                eot_score=eot_score,
            ),
        )

    def matches_text(self, text: str | None) -> bool:
        return bool(text and self.evidence.transcript_sha256 == committed_turn_text_sha256(text))

    def as_metadata(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "decision": "commit",
            "evidence": self.evidence.as_metadata(),
        }


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _nonempty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _score(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return result


def _optional_score(value: object) -> float | None:
    if value is None:
        return None
    return _score(value, field="eot_score")
