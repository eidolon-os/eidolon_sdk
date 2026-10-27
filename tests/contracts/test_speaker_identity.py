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


def test_controlled_trial_is_explicit_and_unknown_has_no_personal_details():
    value=SpeakerIdentityObservation(status='identified', owner_id='o', source=source(),
        confidence='controlled_trial', reason='voice_match', person_id='p', person_revision=1,
        profile_id='v', profile_revision=1, model_id='m', weights_hash='a'*64,
        preprocessing_version='v', scoring_version='v', decision_version='trial')
    assert value.confidence != 'validated'
    with pytest.raises(ValidationError):
        SpeakerIdentityObservation(status='uncertain', owner_id='o', confidence='none',
            reason='short', display_name='somebody')

@pytest.mark.parametrize('change', [{'issued_at': float('inf')}, {'expires_at': float('nan')}])
def test_nonfinite_observation_times_are_invalid(change):
    with pytest.raises(ValidationError):
        SpeakerIdentityObservation(status='unavailable',owner_id='o',confidence='none',reason='timeout',**change)


def test_observation_attestation_cannot_renew_expired_or_mismatched_evidence():
    import time
    from eidolon_sdk.biz.speaker_attestation import sign_observation
    now=time.time()
    value=SpeakerIdentityObservation(status='unavailable',owner_id='o',session_id='s',turn_id='t',
        confidence='none',reason='timeout',issued_at=now-20,expires_at=now-10)
    with pytest.raises(ValueError):sign_observation(value,secret='x'*32,text='hello')
    value=value.model_copy(update={'issued_at':now,'expires_at':now+10,'source':source()})
    with pytest.raises(ValueError):sign_observation(value,secret='x'*32,text='hello')
