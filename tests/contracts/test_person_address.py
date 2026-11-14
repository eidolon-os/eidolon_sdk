"""The one definition of what a person is called aloud."""

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.person import PersonProfile, address_as
from eidolon_sdk.biz.person_face import FaceCandidate, FaceFeatures, FaceTemplate
from eidolon_sdk.biz.speaker_identity import SpeakerCandidate

FEATURES = {"model_id": "m", "weights_hash": "a" * 64, "preprocessing_version": "p", "vector": [0.1, -0.2, 0.3]}


def test_a_person_is_addressed_as_they_asked_or_else_by_their_listed_name():
    assert address_as("劲松松", PersonProfile(preferred_name="松哥")) == "松哥"
    assert address_as("劲松松", PersonProfile()) == "劲松松"
    # A blank answer is no answer: model_construct stands for stored data that
    # never passed the contract's own whitespace stripping.
    assert address_as(" 劲松松 ", PersonProfile.model_construct(preferred_name="  ")) == "劲松松"
    assert address_as("劲松松", PersonProfile.model_construct(preferred_name=" 松哥 ")) == "松哥"


def test_recognition_candidates_carry_the_address_and_no_other_name():
    template = FaceTemplate(revision=1, features=FaceFeatures(**FEATURES))
    assert FaceCandidate(person_id="a" * 32, address_as="松哥", templates=[template]).address_as == "松哥"
    assert "display_name" not in FaceCandidate.model_fields
    assert "display_name" not in SpeakerCandidate.model_fields
    assert SpeakerCandidate.model_fields["address_as"].is_required()
    for invalid in ({}, {"address_as": ""}, {"address_as": "x" * 129}, {"display_name": "松哥"}):
        with pytest.raises(ValidationError):
            FaceCandidate(person_id="a" * 32, templates=[template], **invalid)
