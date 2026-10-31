import pytest
from pydantic import ValidationError
from eidolon_sdk.biz.candidate_evidence import CandidateEvidence


def payload():
    return dict(snapshot_revision='a' * 64, audio_sha256='b' * 64, observation=dict(
        status='compared', owner_id='o', session_id='s', turn_id='t',
        source=dict(request_id='t', session_id='s', input_id='mic', generation=1,
                    sample_rate=16000, start_sample=0, end_sample=32000, channel='mobile'),
        model_id='m', weights_hash='a' * 64, preprocessing_version='v',
        backend_version='b', policy_version='p', reason='compared', issued_at=1, expires_at=11,
        evidence=[dict(person_id='p', person_revision=1, maturity='candidate', is_named=False,
                       profile_id='v', profile_revision=1, llr=5.0, posterior=0.98)],
        posterior_unknown=0.02, decisions=dict(candidate_evidence='p'),
        audio_quality=dict(audio_ms=2000, speech_ms=2000, required_speech_ms=1500, overlap_detected=0)))


def test_bounded_candidate_evidence_roundtrip():
    value = CandidateEvidence(**payload())
    assert CandidateEvidence.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize('field,value', [('decisions', {}), ('session_id', ''),
    ('turn_id', 'other'), ('expires_at', 20), ('status', 'uncertain')])
def test_not_a_candidate_or_wrong_scope_is_rejected(field, value):
    data = payload()
    data['observation'][field] = value
    with pytest.raises(ValidationError):
        CandidateEvidence(**data)


def test_an_established_person_cannot_receive_candidate_evidence():
    data = payload()
    data['observation']['evidence'][0]['maturity'] = 'established'
    with pytest.raises(ValidationError):
        CandidateEvidence(**data)


@pytest.mark.parametrize('speech_ms', [500, 3000])
def test_short_or_impossible_speech_does_not_count(speech_ms):
    data = payload()
    data['observation']['audio_quality']['speech_ms'] = speech_ms
    with pytest.raises(ValidationError):
        CandidateEvidence(**data)


@pytest.mark.parametrize('change', [dict(min_turns=2), dict(min_turns=6),
    dict(min_posterior=float('nan')), dict(min_posterior=0.4), dict(weights_hash='unknown'),
    dict(min_total_speech_ms=100)])
def test_promotion_policy_cannot_weaken_independence_or_model_binding(change):
    from eidolon_sdk.biz.candidate_evidence import CandidatePromotionPolicy
    with pytest.raises(ValidationError):
        CandidatePromotionPolicy(**(dict(version='v', identity_policy_version='p', model_id='m',
            weights_hash='a' * 64, preprocessing_version='v', min_posterior=.95) | change))


def discovery_payload():
    value = payload()['observation']
    value.update(evidence=[], posterior_unknown=0.995, decisions=dict(discovery=True))
    return dict(policy_version='discovery', snapshot_revision='a' * 64, audio_sha256='b' * 64,
        observation=value, sample=dict(model_id='m', weights_hash='a' * 64, preprocessing_version='v',
            vector=[1, 0], speech_ms=2000, quality={'overlap_detected': 0}))


def test_discovery_requires_explicit_single_speaker_evidence_and_matching_model():
    from eidolon_sdk.biz.candidate_evidence import CandidateDiscovery
    assert CandidateDiscovery(**discovery_payload()).observation.decisions.discovery
    data = discovery_payload()
    data['observation']['decisions'] = {}
    with pytest.raises(ValidationError, match='someone not enrolled'):
        CandidateDiscovery(**data)
    for quality in ({}, {'overlap_detected': 1}):
        data = discovery_payload()
        data['sample']['quality'] = quality
        with pytest.raises(ValidationError, match='non-overlap'):
            CandidateDiscovery(**data)
    data = discovery_payload()
    data['sample']['model_id'] = 'other'
    with pytest.raises(ValidationError, match='model'):
        CandidateDiscovery(**data)


@pytest.mark.parametrize('overlap', [None, 1, .5])
def test_candidate_evidence_requires_explicit_non_overlap(overlap):
    data = payload()
    data['observation']['audio_quality']['overlap_detected'] = overlap
    with pytest.raises(ValidationError, match='non-overlap'):
        CandidateEvidence(**data)
