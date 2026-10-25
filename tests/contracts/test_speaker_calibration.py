"""Release consumption fails closed; these values are synthetic, not calibration."""

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.speaker_calibration import SpeakerAdmissionCalibration, load_calibration


def artifact():
    return dict(
        validation_state="calibrated",
        calibration_id="synthetic-only",
        model_id="test",
        weights_hash="a" * 64,
        preprocessing_version="test-v1",
        threshold=0.6,
        max_allowed_speakers=1,
        min_audio_ms=1500,
        max_audio_ms=8000,
        registration_min_similarity=0.7,
        trial_min_similarity=0.7,
        evidence_sha256="b" * 64,
    )


@pytest.mark.parametrize(
    "field", ["threshold", "registration_min_similarity", "trial_min_similarity", "evidence_sha256"]
)
def test_release_has_no_implicit_acceptance_defaults(field):
    value = artifact()
    del value[field]
    with pytest.raises(ValidationError):
        SpeakerAdmissionCalibration.model_validate(value)


@pytest.mark.parametrize("field", ["device_id", "companion_id", "owner_id"])
def test_model_release_cannot_bind_personal_authority(field):
    with pytest.raises(ValidationError):
        SpeakerAdmissionCalibration.model_validate({**artifact(), field: "arbitrary"})


def test_content_digest_survives_wire_and_changes_with_criteria(tmp_path):
    value = SpeakerAdmissionCalibration(**artifact())
    path = tmp_path / "calibration.json"
    path.write_text(value.model_dump_json())
    assert load_calibration(str(path)).digest == value.digest
    changed = SpeakerAdmissionCalibration(**{**artifact(), "threshold": 0.65})
    assert changed.calibration_id == value.calibration_id
    assert changed.digest != value.digest


def test_loader_does_not_echo_missing_or_malformed_artifacts(tmp_path):
    with pytest.raises(ValueError, match="^SPEAKER_VERIFIED_CALIBRATION_REQUIRED$"):
        load_calibration("")
    path = tmp_path / "private.json"
    for raw in ("private content", "x" * 16385):
        path.write_text(raw)
        with pytest.raises(ValueError, match="^SPEAKER_VERIFIED_CALIBRATION_INVALID$"):
            load_calibration(str(path))


def test_controlled_trial_is_explicit_and_does_not_claim_evidence():
    value = artifact()
    value.update(validation_state="controlled_trial")
    del value["evidence_sha256"]
    trial = SpeakerAdmissionCalibration(**value)
    assert trial.validation_state == "controlled_trial"
    assert trial.evidence_sha256 is None
    assert trial.digest != SpeakerAdmissionCalibration(**artifact()).digest
