import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.voiceprint import SpeakerExtractionReadiness, VoiceAudioRequest


def test_extraction_readiness_does_not_authorize_admission():
    ready = SpeakerExtractionReadiness(state='ready', extraction_ready=True)
    assert ready.admission_ready is False
    with pytest.raises(ValidationError):
        SpeakerExtractionReadiness(state='ready', extraction_ready=True, admission_ready=True)


def test_extraction_input_has_no_device_or_companion_authority():
    for field in ('device_id', 'companion_id', 'profile_id'):
        with pytest.raises(ValidationError):
            VoiceAudioRequest.model_validate({'pcm_base64': 'AAAA', field: 'arbitrary'})
