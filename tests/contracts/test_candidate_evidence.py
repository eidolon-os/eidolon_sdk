import pytest
from pydantic import ValidationError
from eidolon_sdk.biz.candidate_evidence import CandidateEvidence


def payload():
    return dict(snapshot_revision='a' * 64, audio_sha256='b' * 64, observation=dict(
        status='identified', owner_id='o', session_id='s', turn_id='t',
        source=dict(request_id='t', session_id='s', input_id='mic', generation=1,
                    sample_rate=16000, start_sample=0, end_sample=32000),
        person_id='p', person_revision=1, profile_id='v', profile_revision=1,
        model_id='m', weights_hash='a' * 64, preprocessing_version='v',
        decision_version='trial', scoring_version='cosine', confidence='controlled_trial',
        maturity='candidate', reason='voice_match', issued_at=1, expires_at=11,
        audio_quality=dict(audio_ms=2000, speech_ms=2000, required_speech_ms=1500)))


def test_bounded_candidate_evidence_roundtrip():
    value = CandidateEvidence(**payload())
    assert CandidateEvidence.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize('field,value', [('maturity', 'established'), ('session_id', ''),
    ('turn_id', 'other'), ('expires_at', 20), ('confidence', 'unvalidated')])
def test_not_a_candidate_or_wrong_scope_is_rejected(field, value):
    data = payload()
    data['observation'][field] = value
    with pytest.raises(ValidationError):
        CandidateEvidence(**data)


@pytest.mark.parametrize('speech_ms', [500, 3000])
def test_short_or_impossible_speech_does_not_count(speech_ms):
    data = payload()
    data['observation']['audio_quality']['speech_ms'] = speech_ms
    with pytest.raises(ValidationError):
        CandidateEvidence(**data)
