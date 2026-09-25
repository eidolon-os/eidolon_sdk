import pytest
from pydantic import ValidationError
from eidolon_sdk.biz.control.shared_session import SharedSessionInvitation
from eidolon_sdk.device_foundation.v1.testing import named_device_instance_id


def payload():
    return dict(
        session_id="shared-1",
        device_ref=dict(device_instance_id=named_device_instance_id("box"),
                        owner_domain_id="owner-domain-1", owner_domain_generation=1,
                        claim_generation=1, trust_epoch=1),
        deadline_ms=2000,
        channel=dict(channel_id="temporary-1", purpose="shared-session",
                     kinds=["reliable-data", "audio"], binding_format="test/v1",
                     issued_at_ms=1000, expires_at_ms=3000, opaque_binding="c2VjcmV0"),
    )


def test_invitation_round_trip_and_redacted_credentials():
    import json
    value = SharedSessionInvitation.model_validate_json(json.dumps(payload()))
    assert SharedSessionInvitation.model_validate_json(value.model_dump_json()) == value
    assert "c2VjcmV0" not in repr(value)
    assert "c2VjcmV0" in value.model_dump_json()


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", "1"), ("schema_version", 1.0),
    ("deadline_ms", 1000), ("deadline_ms", 3001), ("deadline_ms", "2000"),
    ("session_id", ""), ("companion_id", "invented"), ("return_channel", {}),
])
def test_invitation_rejects_ambiguous_or_duplicate_authority(field, value):
    import json
    raw = payload()
    raw[field] = value
    with pytest.raises(ValidationError):
        SharedSessionInvitation.model_validate_json(json.dumps(raw))


def test_invitation_cannot_relabel_a_standing_channel():
    import json
    raw = payload()
    raw["channel"]["purpose"] = "device-session"
    with pytest.raises(ValidationError):
        SharedSessionInvitation.model_validate_json(json.dumps(raw))


def test_invitation_uses_existing_envelope_target_and_deadline():
    import json
    value = SharedSessionInvitation.model_validate_json(json.dumps(payload()))
    command = value.command(command_id="invite-1")
    assert command["op"] == "shared-session.invite"
    assert command["id"] == "invite-1"
    assert command["dst"]["id"] == value.device_ref.device_instance_id
    assert command["ts"] + command["ttl_ms"] == value.deadline_ms
    assert command["payload"] == value.model_dump(mode="json")
    assert command["src"] == {"type": "channel", "id": "channel-provider"}
    with pytest.raises(ValueError):
        value.command(command_id="")
