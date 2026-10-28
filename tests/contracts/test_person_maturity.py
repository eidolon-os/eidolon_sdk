import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.person import PersonCreate, PersonProfile, PersonUpdate, PersonView


def test_legacy_person_defaults_and_candidate_roundtrip():
    legacy = PersonCreate(person_id="a" * 32, display_name="甲")
    assert legacy.maturity == "established" and legacy.is_named
    candidate = PersonCreate(person_id="b" * 32, display_name="未命名用户",
                             maturity="candidate", is_named=False)
    view = PersonView(**candidate.model_dump(), owner_id="owner", status="active", revision=1)
    assert PersonView.model_validate_json(view.model_dump_json()) == view
    assert view.maturity == "candidate" and not view.is_named


def test_management_update_cannot_assert_evidence_promotion():
    fields = dict(expected_revision=1, display_name="甲", status="active", profile=PersonProfile())
    assert PersonUpdate(**fields).is_named is None
    with pytest.raises(ValidationError):
        PersonUpdate(**fields, maturity="established")
