import pytest
from pydantic import ValidationError
from eidolon_sdk.biz.control.shared_session import SharedSessionSelection
from eidolon_sdk.device_foundation.v1.testing import named_device_instance_id


def selection():
    refs = [
        dict(
            device_instance_id=named_device_instance_id(name),
            owner_domain_id="owner-domain-1",
            owner_domain_generation=1,
            claim_generation=1,
            trust_epoch=1,
        )
        for name in ("stackchan", "box")
    ]
    return dict(
        session_id="discussion-1", devices=refs, input_device_id=refs[0]["device_instance_id"]
    )


def test_selection_is_mobile_independent_and_round_trips():
    value = SharedSessionSelection.model_validate(selection())
    assert SharedSessionSelection.model_validate(value.model_dump(mode="json")) == value
    assert value.input_device_id == value.devices[0].device_instance_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", "1"),
        ("schema_version", 2),
        ("session_id", ""),
        ("session_id", "bad id"),
        ("input_device_id", named_device_instance_id("missing")),
        ("owner_id", "forged"),
        ("companion_bindings", {}),
        ("room_name", "permanent-room"),
    ],
)
def test_selection_rejects_ambiguous_or_extra_authority(field, value):
    payload = selection()
    payload[field] = value
    with pytest.raises(ValidationError):
        SharedSessionSelection.model_validate(payload)


@pytest.mark.parametrize("change", ["duplicate", "single", "too_many", "domain", "generation"])
def test_selection_requires_one_bounded_owner_domain(change):
    payload = selection()
    if change == "duplicate":
        payload["devices"][1] = payload["devices"][0]
    elif change == "single":
        payload["devices"] = payload["devices"][:1]
    elif change == "too_many":
        payload["devices"] *= 9
    elif change == "domain":
        payload["devices"][1]["owner_domain_id"] = "other-domain"
    else:
        payload["devices"][1]["owner_domain_generation"] = 2
    with pytest.raises(ValidationError):
        SharedSessionSelection.model_validate(payload)
