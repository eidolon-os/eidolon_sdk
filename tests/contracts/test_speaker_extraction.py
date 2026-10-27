import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.voiceprint import SpeakerExtractionReadiness, VoiceAudioRequest


def test_extraction_readiness_does_not_authorize_admission():
    ready = SpeakerExtractionReadiness(state='ready', extraction_ready=True)
    assert "admission_ready" not in ready.model_dump()
    with pytest.raises(ValidationError):
        SpeakerExtractionReadiness(state='ready', extraction_ready=True, admission_ready=True)


def test_extraction_input_has_no_device_or_companion_authority():
    for field in ('device_id', 'companion_id', 'profile_id'):
        with pytest.raises(ValidationError):
            VoiceAudioRequest.model_validate({'pcm_base64': 'AAAA', field: 'arbitrary'})


def test_normalized_evidence_fingerprint_survives_wire_roundtrips():
    from eidolon_sdk.biz.voiceprint import ExtractedSample, enrollment_evidence_digest
    sample = ExtractedSample(model_id='test', weights_hash='a'*64,
                             preprocessing_version='v1', vector=[.1,.2,.3], speech_ms=4000)
    expected = enrollment_evidence_digest({'0':sample})
    for _ in range(5):
        sample = ExtractedSample.model_validate_json(sample.model_dump_json())
        assert enrollment_evidence_digest({'0':sample}) == expected
