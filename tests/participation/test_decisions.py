"""Untrusted decision results must never become execution permissions."""

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.participation import DecisionRequest, DecisionResult, validate_proposal


def request():
    return DecisionRequest.model_validate(
        {
            "schema_version": 2,
            "decision_id": "d1",
            "context_ref": "team-chat",
            "context_version": 2,
            "membership_revision": 3,
            "cancellation_epoch": 4,
            "timeout_ms": 300,
            "trigger": {
                "message_id": "m1",
                "author_kind": "user",
                "author_id": "owner",
                "text": "悟空先说，八戒补充",
            },
            "user_request": {"message_id":"m1", "author_kind":"user", "author_id":"owner", "text":"悟空先说，八戒补充"},
            "context": {
                "recent_messages": [],
                "summary": "旅行安排",
                "pending_requirements": ["八戒随后补充"],
            },
            "candidates": [
                {"companion_id": "wukong", "description": "喜欢探索"},
                {"companion_id": "bajie", "description": "关注休息"},
            ],
            "constraints": {
                "allowed_actions": ["respond", "clarify", "wait", "finish"],
                "max_next_speakers": 1,
            },
        }
    )


def result(**changes):
    data = dict(
        schema_version=2,
        decision_id="d1",
        context_ref="team-chat",
        context_version=2,
        membership_revision=3,
        cancellation_epoch=4,
        status="decided",
        proposal={"action": "respond", "participants": ["wukong"]},
        policy_version="p1",
        model_version="model1",
    )
    data.update(changes)
    return DecisionResult.model_validate(data)


def test_json_roundtrip_preserves_chinese_and_accepted_proposal():
    req = DecisionRequest.model_validate_json(request().model_dump_json())
    assert req.trigger.text == "悟空先说，八戒补充"
    validate_proposal(req, result())


@pytest.mark.parametrize(
    "changes",
    [
        {"decision_id": "other"},
        {"context_ref": "private-chat"},
        {"context_version": 1},
        {"membership_revision": 2},
        {"cancellation_epoch": 3},
        {"proposal": {"action": "respond", "participants": ["stranger"]}},
        {"proposal": {"action": "respond", "participants": ["wukong", "bajie"]}},
    ],
)
def test_rejects_stale_or_outside_scope_proposal(changes):
    with pytest.raises(ValueError):
        validate_proposal(request(), result(**changes))


def test_abstention_is_distinct_from_wait():
    validate_proposal(request(), result(status="abstained", proposal=None))
    validate_proposal(request(), result(proposal={"action": "wait", "participants": []}))
    with pytest.raises(ValidationError):
        result(status="abstained")


@pytest.mark.parametrize(
    "proposal",
    [
        {"action": "respond", "participants": []},
        {"action": "respond", "participants": ["wukong", "wukong"]},
        {"action": "wait", "participants": ["wukong"]},
        {"action": "finish", "participants": ["wukong"]},
        {"action": "clarify", "participants": ["wukong", "bajie"]},
    ],
)
def test_rejects_contradictory_actions(proposal):
    with pytest.raises(ValidationError):
        result(proposal=proposal)


def test_rejects_disallowed_action():
    data = request().model_dump(mode="json")
    data["constraints"]["allowed_actions"] = ["respond"]
    with pytest.raises(ValueError):
        validate_proposal(
            DecisionRequest.model_validate(data),
            result(proposal={"action": "finish", "participants": []}),
        )


def test_rejects_oversize_context_instead_of_truncation():
    data = request().model_dump(mode="json")
    data["trigger"]["text"] = "a" * 32769
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(data)


@pytest.mark.parametrize("version", [True, "2", 1])
def test_version_does_not_coerce(version):
    data = request().model_dump(mode="json")
    data["schema_version"] = version
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(data)


def test_candidate_set_cannot_contain_duplicates():
    data = request().model_dump(mode="json")
    data["candidates"].append(data["candidates"][0])
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(data)
