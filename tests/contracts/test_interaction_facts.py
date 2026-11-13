"""InteractionFacts: thinking is optional for senders, never for old receivers."""
import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.presentation.interaction import InteractionFacts

BASE = {"version": 1, "session_id": "session", "policy_revision": 1, "sequence": 1,
        "user_speaking": False, "agent_speaking": False}


def test_thinking_defaults_to_false_for_a_sender_that_does_not_report_it():
    assert InteractionFacts.model_validate(BASE).agent_thinking is False
    assert InteractionFacts.model_validate({**BASE, "agent_thinking": True}).agent_thinking is True


def test_thinking_is_a_strict_boolean_and_other_fields_stay_closed():
    with pytest.raises(ValidationError):
        InteractionFacts.model_validate({**BASE, "agent_thinking": 1})
    with pytest.raises(ValidationError):
        InteractionFacts.model_validate({**BASE, "agent_mood": "calm"})
