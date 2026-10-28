import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.person_observation import PersonObservationFeedback


def packet(**changes):
    return dict(sequence=1, session_id="s", conversation_id="s", turn_id="t",
                status="identified", person_id="p", display_name="A",
                confidence="controlled_trial", reason="voice_match",
                issued_at=100, expires_at=110) | changes


def test_voice_feedback_preserves_lease_and_subject():
    value = PersonObservationFeedback(**packet())
    assert value.subject_role == "speaker"
    assert value.modalities == ["voice"]
    assert value.expires_at == 110


@pytest.mark.parametrize("changes", [
    {"sequence": 0}, {"sequence": True}, {"sequence": "1"},
    {"conversation_id": "other"}, {"expires_at": 111},
    {"issued_at": float("nan")}, {"status": "unknown"},
    {"confidence": "none"}, {"display_name": None},
    {"modalities": ["voice", "face"]}, {"modalities": ["face"]},
    {"subject_role": "visible_person"},
])
def test_feedback_rejects_ambiguous_or_unscoped_identity(changes):
    with pytest.raises(ValidationError):
        PersonObservationFeedback(**packet(**changes))


def test_reserved_visible_subject_is_distinct_from_speaker():
    value = PersonObservationFeedback(**packet(subject_role="visible_person", modalities=["face"]))
    assert value.subject_role != "speaker"
