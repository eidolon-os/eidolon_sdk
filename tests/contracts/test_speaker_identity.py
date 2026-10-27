import pytest
from pydantic import ValidationError
from eidolon_sdk.biz.speaker_identity import SpeakerIdentityObservation, SpeakerEvidenceSource

def source():
    return SpeakerEvidenceSource(request_id='r', input_id='mic', generation=1,
        sample_rate=16000, start_sample=0, end_sample=16000)

def test_uncertainty_is_not_a_person_or_probability():
    result = SpeakerIdentityObservation(status='uncertain', owner_id='o', source=source(),
        confidence='unvalidated', cosine_similarity=.9, reason='controlled_trial')
    assert result.person_id is None
    with pytest.raises(ValidationError):
        SpeakerIdentityObservation(**(result.model_dump() | {'person_id':'p'}))
    with pytest.raises(ValidationError):
        SpeakerIdentityObservation(**(result.model_dump() | {'status':'identified'}))

def test_conclusive_identity_requires_versions_and_evidence_range():
    result = SpeakerIdentityObservation(status='identified', owner_id='o', source=source(),
        confidence='validated', reason='matched', person_id='p', person_revision=1,
        profile_id='v', profile_revision=2, model_id='m', weights_hash='a'*64,
        preprocessing_version='1', scoring_version='1', decision_version='1')
    assert result.source.generation == 1
    with pytest.raises(ValidationError):
        SpeakerEvidenceSource(**(source().model_dump() | {'end_sample':0}))


def test_voiceprint_profiles_require_a_person_from_creation():
    from eidolon_sdk.biz.voiceprint import SpeakerProfileView

    fields = dict(profile_id='v', display_name='Alice', revision=1, enrollment_id='e')
    assert SpeakerProfileView(person_id='p', **fields).person_id == 'p'
    for invalid in ({}, {'person_id': None}, {'person_id': ''}):
        with pytest.raises(ValidationError):
            SpeakerProfileView(**fields, **invalid)
