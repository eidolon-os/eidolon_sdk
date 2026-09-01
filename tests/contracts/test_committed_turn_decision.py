"""Contract tests for provider-neutral committed turn decisions."""

from __future__ import annotations

import pytest

from eidolon_sdk.biz.dialogue_control import CommittedTurnDecision, TurnCommitBoundary


def _decision(text: str = "我们换个话题吧") -> CommittedTurnDecision:
    return CommittedTurnDecision.create(
        text=text,
        boundary=TurnCommitBoundary.FRAMEWORK_COMPLETED,
        eot_score=0.82,
    )


def test_committed_turn_decision_round_trips_and_binds_exact_text() -> None:
    original = _decision()
    metadata = original.as_metadata()
    parsed = CommittedTurnDecision.from_metadata(metadata)

    assert parsed == original
    assert parsed.matches_text(" 我们换个话题吧 ") is True
    assert parsed.matches_text("我们换个问题吧") is False
    assert parsed.evidence.transcript_final is True
    assert parsed.evidence.vad_terminal is True
    assert "intent" not in metadata
    assert "source" not in metadata


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": 2},
        {"decision": "hold"},
        {"evidence": {"boundary": "framework_completed_turn"}},
    ],
)
def test_committed_turn_decision_rejects_malformed_contract(mutation) -> None:
    metadata = _decision().as_metadata()
    metadata.update(mutation)

    with pytest.raises(ValueError):
        CommittedTurnDecision.from_metadata(metadata)


def test_committed_turn_decision_rejects_non_terminal_evidence() -> None:
    metadata = _decision().as_metadata()
    metadata["evidence"] = {
        **metadata["evidence"],
        "vad_terminal": False,
    }

    with pytest.raises(ValueError, match="final and VAD-terminal"):
        CommittedTurnDecision.from_metadata(metadata)
