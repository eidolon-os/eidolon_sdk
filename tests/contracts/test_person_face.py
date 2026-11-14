import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.person_face import (
    FaceCandidate,
    FaceCandidates,
    FaceFeatures,
    FaceRecognitionConsent,
    FaceTemplate,
    PersonFaceFeaturesWrite,
    PersonFaceRecognitionEnable,
    PersonFaceState,
)

CONSENT = {"consent_version": "face-recognition-consent/2026-11-14", "statement": "s", "attested": True}
FEATURES = {
    "model_id": "m",
    "weights_hash": "a" * 64,
    "preprocessing_version": "p",
    "vector": [0.1, -0.2, 0.3],
}


def test_state_defaults_to_not_configured_and_reads_older_payloads():
    state = PersonFaceState.model_validate({"person_id": "p", "revision": 1, "has_image": True})
    assert state.recognition_state == "not_configured"
    assert state.recognition_consent_version is None


def test_consent_must_be_attested():
    assert FaceRecognitionConsent(**CONSENT).attested is True
    with pytest.raises(ValidationError):
        FaceRecognitionConsent(**(CONSENT | {"attested": False}))
    with pytest.raises(ValidationError):
        PersonFaceRecognitionEnable(expected_revision=1, consent={"consent_version": "v"})


def test_enabling_needs_an_existing_photo_revision():
    with pytest.raises(ValidationError):
        PersonFaceRecognitionEnable(expected_revision=0, consent=CONSENT)
    with pytest.raises(ValidationError):
        PersonFaceRecognitionEnable(expected_revision=1, consent=CONSENT, features=FEATURES)


@pytest.mark.parametrize(
    "bad",
    [
        {"vector": [1.0]},
        {"vector": [float("nan"), 1.0]},
        {"weights_hash": "xyz"},
        {"feature_schema_version": 2},
    ],
)
def test_features_are_bounded(bad):
    with pytest.raises(ValidationError):
        FaceFeatures(**(FEATURES | bad))


def test_features_write_binds_consent_and_features():
    write = PersonFaceFeaturesWrite(expected_revision=2, consent=CONSENT, features=FEATURES)
    assert write.features.feature_schema_version == 1


def test_candidates_hold_each_person_once():
    candidate = FaceCandidate(
        person_id="a" * 32,
        display_name="Ada",
        templates=[FaceTemplate(revision=1, features=FEATURES)],
    )
    assert FaceCandidates(owner_id="o", revision="b" * 64, persons=[candidate]).persons
    with pytest.raises(ValidationError):
        FaceCandidates(owner_id="o", revision="b" * 64, persons=[candidate, candidate])
    with pytest.raises(ValidationError):
        FaceCandidate(person_id="a" * 32, display_name="Ada", templates=[])
