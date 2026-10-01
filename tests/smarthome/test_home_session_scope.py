import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.smarthome import HomeCommandRequest, HomeSessionScope


@pytest.mark.parametrize("field", ["owner_id", "companion_id", "device_ref", "session_id"])
@pytest.mark.parametrize("value", [None, "", " ", " identity", 1])
def test_home_interaction_requires_canonical_identity(field, value):
    body = {
        "owner_id": "owner", "companion_id": "companion", "device_ref": "panel",
        "session_id": "voice", "turn_id": "turn", "utterance": "开灯", field: value,
    }
    with pytest.raises(ValidationError):
        HomeCommandRequest.model_validate(body)


def test_home_scope_cannot_be_mutated_or_carry_persona_memory():
    scope = HomeSessionScope(
        owner_id="owner", companion_id="companion", device_ref="panel", session_id="voice",
    )
    with pytest.raises(ValidationError):
        scope.companion_id = "other"
    with pytest.raises(ValidationError):
        HomeCommandRequest(**scope.model_dump(), turn_id="turn", utterance="开灯", memory="history")
