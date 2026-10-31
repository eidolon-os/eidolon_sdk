"""Per-Person, per-duration calibration contracts (design §3.3)."""

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.speaker_identity import (
    CohortReference,
    DurationBand,
    RecognitionCalibration,
    SpeakerRecognitionPolicy,
)
from eidolon_sdk.biz.voiceprint import (
    CalibrationCrop,
    EnrollmentEvaluationRequest,
    EnrollmentEvidence,
    EnrollmentSample,
    ExtractedSample,
    VoiceTemplate,
    enrollment_evidence_digest,
)


def bands():
    return [
        DurationBand(name="short", min_speech_ms=600, floor=0.3, margin=0.1),
        DurationBand(name="medium", min_speech_ms=1200, floor=0.3, margin=0.08),
        DurationBand(name="long", min_speech_ms=2500, floor=0.3, margin=0.06),
    ]


def calibration(**change):
    return RecognitionCalibration(**({
        "version": "v", "max_false_accept": 0.005, "min_genuine_acceptance": 0.8,
        "min_genuine_scores": 4, "bands": bands(),
        "cohort": CohortReference(path="impostor-cohort.npz", sha256="a" * 64, speakers=70),
    } | change))


def policy(**change):
    return SpeakerRecognitionPolicy(**({
        "version": "v3", "model_id": "m", "weights_hash": "b" * 64,
        "preprocessing_version": "p", "threshold": 0.55, "min_person_margin": 0.1,
        "min_speech_ms": 600, "calibration": calibration(),
    } | change))


def sample(**change):
    return ExtractedSample(**({"model_id": "m", "weights_hash": "b" * 64,
        "preprocessing_version": "p", "vector": [0.6, 0.8], "speech_ms": 4000} | change))


def test_a_probe_falls_in_the_last_band_it_reaches():
    value = calibration()
    assert value.band(599) is None
    assert value.band(600).name == "short"
    assert value.band(1199).name == "short"
    assert value.band(1200).name == "medium"
    assert value.band(30000).name == "long"


@pytest.mark.parametrize("ordered", [
    lambda b: [b[1], b[0], b[2]],
    lambda b: [b[0], b[0].model_copy(update={"name": "again"}), b[2]],
    lambda b: [b[0], b[1].model_copy(update={"name": "short"}), b[2]],
])
def test_bands_are_distinct_and_ascending(ordered):
    with pytest.raises(ValidationError):
        calibration(bands=ordered(bands()))


def test_calibrated_bands_start_at_the_extraction_floor():
    assert policy().calibration.bands[0].min_speech_ms == 600
    with pytest.raises(ValidationError):
        policy(min_speech_ms=800, min_unknown_speech_ms=1500)


def test_an_uncalibrated_policy_still_reads():
    assert policy(calibration=None).calibration is None


@pytest.mark.parametrize("far", [0, 0.2])
def test_false_accept_target_is_bounded(far):
    with pytest.raises(ValidationError):
        calibration(max_false_accept=far)


def test_cohort_is_a_file_beside_the_model_not_a_path_elsewhere():
    for path in ("../x.npz", "dir/x.npz", ""):
        with pytest.raises(ValidationError):
            CohortReference(path=path, sha256="a" * 64, speakers=1)


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
        template=windowed, trial=windowed, registration_min_similarity=1, trial_min_similarity=1)
    assert "crops" not in evaluation.template.model_dump()
    assert "crops" not in evaluation.trial.model_dump()


def test_a_sample_without_windows_digests_the_same_as_before():
    assert (enrollment_evidence_digest({"0": sample()})
            == enrollment_evidence_digest({"0": EnrollmentSample.model_validate(sample())}))
