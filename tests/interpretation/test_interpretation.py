"""An interpretation result is a proposal; it must never widen what the caller offered."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.interpretation import (
    InterpretationError,
    InterpretationRequest,
    InterpretationResult,
    Proposal,
    validate_proposal,
)


def request(**overrides):
    body = {
        "interpretation_id": "i1",
        "domain": "smarthome",
        "utterance": "打开空调",
        "origin": {"device_ref": "korvo-1", "area_id": "living"},
        "candidates": [
            {"ref": "living.ac", "name": "客厅空调", "kind": "climate", "area_id": "living"},
            {"ref": "master.ac", "name": "主卧空调", "kind": "climate", "area_id": "master"},
        ],
        "areas": [{"area_id": "living", "name": "客厅"}, {"area_id": "master", "name": "主卧"}],
        "timeout_ms": 200,
    }
    body.update(overrides)
    return InterpretationRequest.model_validate(body)


def result(proposal, **overrides):
    body = {
        "interpretation_id": "i1",
        "status": "decided",
        "proposal": proposal,
        "policy_version": "rules-1",
        "model_version": "rules-1",
    }
    body.update(overrides)
    return InterpretationResult.model_validate(body)


def control(*targets, status="resolved"):
    return {"intent": "control", "target_status": status, "targets": list(targets),
            "action": {"trait": "on_off", "command": "on"}}


def test_request_rejects_inconsistent_snapshots():
    with pytest.raises(ValidationError, match="DUPLICATE_CANDIDATE"):
        request(candidates=[{"ref": "a", "name": "灯", "kind": "light"}] * 2)
    with pytest.raises(ValidationError, match="ORIGIN_AREA_UNKNOWN"):
        request(origin={"area_id": "study"})
    with pytest.raises(ValidationError, match="CANDIDATE_AREA_UNKNOWN"):
        request(candidates=[{"ref": "a", "name": "灯", "kind": "light", "area_id": "study"}])
    with pytest.raises(ValidationError, match="SCHEMA_VERSION_MUST_BE_INTEGER"):
        request(schema_version="1")


@pytest.mark.parametrize(
    "proposal, code",
    [
        ({"intent": "unrelated", "target_status": "none", "targets": ["a"]}, "UNRELATED_CARRIES_TARGET"),
        ({"intent": "control", "target_status": "resolved", "targets": [],
          "action": {"trait": "on_off", "command": "on"}}, "RESOLVED_WITHOUT_TARGET"),
        (control("living.ac", status="ambiguous"), "AMBIGUOUS_NEEDS_CANDIDATES"),
        ({"intent": "control", "target_status": "resolved", "targets": ["living.ac"]}, "CONTROL_WITHOUT_ACTION"),
        ({"intent": "query", "target_status": "none", "targets": ["a"]}, "NONE_CARRIES_TARGET"),
    ],
)
def test_proposal_shapes(proposal, code):
    with pytest.raises(ValidationError, match=code):
        Proposal.model_validate(proposal)


def test_abstaining_is_distinct_from_deciding_unrelated():
    with pytest.raises(ValidationError, match="PROPOSAL_DOES_NOT_MATCH_STATUS"):
        result(None, status="decided")
    abstained = result(None, status="abstained")
    validate_proposal(request(), abstained)


def test_proposal_cannot_leave_the_offered_candidates():
    validate_proposal(request(), result(control("living.ac")))
    validate_proposal(request(), result(control("living.ac", "master.ac", status="ambiguous")))
    with pytest.raises(ValueError, match="TARGET_OUTSIDE_CANDIDATES"):
        validate_proposal(request(), result(control("kitchen.light")))
    with pytest.raises(ValueError, match="INTERPRETATION_ID_MISMATCH"):
        validate_proposal(request(), result(control("living.ac"), interpretation_id="other"))
    with pytest.raises(ValueError, match="INTENT_NOT_ALLOWED"):
        validate_proposal(request(allowed_intents=["query", "unrelated"]), result(control("living.ac")))


def test_errors_say_whether_retrying_can_help():
    assert InterpretationError("TIMEOUT").retryable
    assert not InterpretationError("INVALID_PROPOSAL").retryable
    with pytest.raises(ValueError):
        InterpretationError("NOPE")


def test_mention_names_what_the_home_lacks_only_when_nothing_matched():
    Proposal.model_validate({"intent": "control", "target_status": "none", "mention": "投影仪",
                             "action": {"trait": "on_off", "command": "on"}})
    with pytest.raises(ValidationError, match="MENTION_ONLY_WHEN_NONE"):
        Proposal.model_validate({**control("living.ac"), "mention": "空调"})


def test_context_payload_is_bounded_and_optional():
    from pydantic import ValidationError
    base=dict(interpretation_id='context',domain='smarthome',utterance='关灯',candidates=(),timeout_ms=1000)
    assert InterpretationRequest(**base).context is None
    assert InterpretationRequest(**base,context={'history':[{'utterance':'开灯'}]}).context['history']
    with pytest.raises(ValidationError,match='CONTEXT_TOO_LARGE'):
        InterpretationRequest(**base,context={'history':'很长的历史'*5000})
