"""Registration windows: same-person evidence that registration gives for free."""

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.voiceprint import (
    CalibrationCrop,
    EnrollmentEvaluationRequest,
    EnrollmentEvidence,
    EnrollmentSample,
    ExtractedSample,
    VoiceTemplate,
    enrollment_evidence_digest,
)


def sample(**change):
    return ExtractedSample(**({"model_id": "m", "weights_hash": "b" * 64,
        "preprocessing_version": "p", "vector": [0.6, 0.8], "speech_ms": 4000} | change))


def test_crop_vectors_stay_short_on_the_wire():
    crop = CalibrationCrop(speech_ms=900, vector=[3.0, 4.0])
    assert crop.vector == [0.6, 0.8]
    long = CalibrationCrop(speech_ms=900, vector=[1 / 3] * 9)
    assert all(len(repr(x)) <= 9 for x in long.vector)
    with pytest.raises(ValidationError):
        CalibrationCrop(speech_ms=900, vector=[0.0, 0.0])
    with pytest.raises(ValidationError):
        CalibrationCrop(speech_ms=900, vector=[float("nan"), 1.0])


def test_an_enrollment_sample_is_a_sample_plus_its_windows():
    crop = CalibrationCrop(speech_ms=900, vector=[1.0, 0.0])
    value = EnrollmentSample(**sample().model_dump(), crops=[crop])
    assert value.sample() == sample()
    assert "crops" not in value.sample().model_dump()
    with pytest.raises(ValidationError):
        EnrollmentSample(**sample().model_dump(), crops=[crop] * 9)


def test_samples_stored_before_windows_existed_still_read():
    stored = sample().model_dump(mode="json")
    assert EnrollmentSample.model_validate(stored).crops == []
    evidence = EnrollmentEvidence.model_validate({
        "enrollment": {"enrollment_id": "e", "profile_id": "v", "state": "collecting",
                       "accepted_samples": 1, "expires_at": 1.0},
        "samples": {"0": stored},
    })
    assert evidence.samples["0"].crops == []


def test_windows_are_part_of_the_evidence_digest():
    plain = {"0": EnrollmentSample(**sample().model_dump())}
    cropped = {"0": EnrollmentSample(**sample().model_dump(),
                                     crops=[CalibrationCrop(speech_ms=900, vector=[1.0, 0.0])])}
    assert enrollment_evidence_digest(plain) != enrollment_evidence_digest(cropped)


def test_evaluation_request_carries_windows_for_every_recording():
    crop = CalibrationCrop(speech_ms=900, vector=[1.0, 0.0])
    one = EnrollmentSample(**sample().model_dump(), crops=[crop])
    request = EnrollmentEvaluationRequest(samples={"0": one, "1": one, "2": one}, trial=one,
                                          recording_sha256="c" * 64)
    again = EnrollmentEvaluationRequest.model_validate_json(request.model_dump_json())
    assert again.trial.crops == [crop]


def test_a_template_without_calibration_reads_as_before():
    stored = {"profile_id": "v", "revision": 1, "sample": sample().model_dump(mode="json")}
    assert VoiceTemplate.model_validate(stored).calibration is None


def test_templates_trials_and_probes_never_carry_windows():
    from eidolon_sdk.biz.voiceprint import EnrollmentEvaluation, SpeakerComparisonRequest

    windowed = EnrollmentSample(**sample().model_dump(),
                                crops=[CalibrationCrop(speech_ms=900, vector=[1.0, 0.0])])
    template = VoiceTemplate(profile_id="v", revision=1, sample=windowed)
    assert "crops" not in template.sample.model_dump()
    probe = SpeakerComparisonRequest(probe=windowed, templates=[template]).probe
    assert type(probe) is ExtractedSample
    evaluation = EnrollmentEvaluation(evidence_digest="d" * 64, recording_sha256="e" * 64,
        template=windowed, trial=windowed)
    assert "crops" not in evaluation.template.model_dump()
    assert "crops" not in evaluation.trial.model_dump()


def test_a_sample_without_windows_digests_the_same_as_before():
    assert (enrollment_evidence_digest({"0": sample()})
            == enrollment_evidence_digest({"0": EnrollmentSample.model_validate(sample())}))
