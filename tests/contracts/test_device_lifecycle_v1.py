from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from eidolon_sdk.device_foundation.v1 import (
    ActorRef,
    BusinessOwnerId,
    DeviceRef,
    ManifestRef,
    OwnerDomainId,
    OwnerAuthorizationContext,
    RemovalIntent,
    RevokeClaim,
    ClaimEventPage,
    ClaimEventRecord,
    revoke_claim_fingerprint,
)


def _ref(*, owner: str = "owner-domain_01", generation: int = 2) -> DeviceRef:
    return DeviceRef(
        device_instance_id="device_01",
        owner_domain_id=owner,
        owner_domain_generation=3,
        claim_generation=generation,
        trust_epoch=4,
    )


def test_device_ref_accepts_deployed_mac_style_instance_id() -> None:
    ref = DeviceRef(
        device_instance_id="10:51:db:7e:24:44",
        owner_domain_id="owner-domain_01",
        owner_domain_generation=3,
        claim_generation=2,
        trust_epoch=4,
    )

    assert ref.device_instance_id == "10:51:db:7e:24:44"
    assert set(ref.model_dump(mode="json")) == {
        "device_instance_id", "owner_domain_id", "owner_domain_generation",
        "claim_generation", "trust_epoch",
    }


def test_owner_domain_business_owner_and_actor_are_nominally_distinct() -> None:
    domain = OwnerDomainId("owner-domain_01")
    owner = BusinessOwnerId("owner_01")
    assert type(domain) is not type(owner)
    with pytest.raises(ValidationError):
        DeviceRef(
            device_instance_id="device_01", owner_domain_id=owner,
            owner_domain_generation=3, claim_generation=2, trust_epoch=4,
        )
    manifest = ManifestRef(
        manifest_id="manifest_01", revision=2, digest="sha256:" + "2" * 64
    )
    assert "digest" not in DeviceRef.model_fields
    assert manifest.digest.startswith("sha256:")


def test_revoke_claim_requires_the_full_exact_device_ref() -> None:
    command = RevokeClaim(
        command_id="revoke_claim_01",
        correlation_id="removal_intent_01",
        device_ref=_ref(),
        reason="owner-removed",
    )

    assert command.device_ref.claim_generation == 2
    with pytest.raises(ValidationError):
        RevokeClaim.model_validate(
            {
                **command.model_dump(),
                "device_ref": {
                    **command.device_ref.model_dump(exclude={"claim_generation"})
                },
            }
        )


def test_owner_authorization_separates_workload_actor_owner_and_audience() -> None:
    now = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    values = {
        "workload_principal_id": "admin_lifecycle_workflow",
        "actor": ActorRef(
            principal_id="controller_01",
            principal_type="controller",
            owner_domain_id="owner-domain_01",
            granted_scopes=("device.claim.revoke",),
            authentication_strength="hardware-backed",
        ),
        "authorized_owner_domain_id": "owner-domain_01",
        "scopes": ("device.claim.revoke",),
        "intent_id": "removal_intent_01",
        "target_device_ref": _ref(),
        "issued_at": now,
        "expires_at": now + timedelta(minutes=1),
    }

    context = OwnerAuthorizationContext(**values)

    assert context.audience == "eidolon-admission"
    assert context.workload_principal_id != context.actor.principal_id
    with pytest.raises(ValidationError, match="do not match"):
        OwnerAuthorizationContext(
            **{**values, "target_device_ref": _ref(owner="owner-domain_02")}
        )
    with pytest.raises(ValidationError, match="exceed"):
        OwnerAuthorizationContext(
            **{
                **values,
                "actor": values["actor"].model_copy(
                    update={"granted_scopes": ("device.read",)}
                ),
            }
        )


def test_removal_intent_freezes_actor_and_exact_device_generation() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    intent = RemovalIntent(
        intent_id="removal_intent_01",
        ingress_request_id="mobile_removal_01",
        device_ref=_ref(),
        actor=ActorRef(
            principal_id="controller_01",
            principal_type="controller",
            owner_domain_id="owner-domain_01",
            granted_scopes=("device.claim.revoke",),
            authentication_strength="hardware-backed",
        ),
        reason="owner-removed",
        claim_command_id="revoke_claim_01",
        state="accepted",
        created_at=now,
        updated_at=now,
    )

    assert intent.device_ref.claim_generation == 2
    assert intent.actor.principal_id == "controller_01"


def test_removal_intent_accepts_uuid_ingress_and_rejects_naive_time() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    values = {
        "intent_id": "removal_intent_01",
        "ingress_request_id": "01A0B1C2-D3E4-4F50-8123-456789ABCDEF",
        "device_ref": _ref(),
        "actor": ActorRef(
            principal_id="controller_01",
            principal_type="controller",
            owner_domain_id="owner-domain_01",
            granted_scopes=("device.claim.revoke",),
            authentication_strength="hardware-backed",
        ),
        "reason": "owner-removed",
        "claim_command_id": "revoke_claim_01",
        "state": "accepted",
        "created_at": now,
        "updated_at": now,
    }
    assert RemovalIntent(**values).ingress_request_id.startswith("01A0")
    with pytest.raises(ValidationError, match="offset"):
        RemovalIntent(**{**values, "created_at": datetime(2026, 8, 23)})


def test_revoke_fingerprint_excludes_retry_ids_but_fences_generation() -> None:
    first = RevokeClaim(
        command_id="revoke_claim_01",
        correlation_id="removal_intent_01",
        device_ref=_ref(generation=2),
        reason="owner-removed",
    )
    retry = first.model_copy(
        update={"command_id": "revoke_claim_02", "correlation_id": "audit_chain_02"}
    )
    newer = first.model_copy(update={"device_ref": _ref(generation=3)})

    assert revoke_claim_fingerprint(first) == revoke_claim_fingerprint(retry)
    assert revoke_claim_fingerprint(first) != revoke_claim_fingerprint(newer)


def test_claim_event_page_requires_a_monotonic_checkpoint_cursor() -> None:
    event = ClaimEventRecord(
        stream_position=7,
        event_id="claim_event_01",
        event_type="live.eidolon.device.claim-revoked.v1",
        device_ref=_ref(),
        aggregate_revision=8,
        correlation_id="removal_intent_01",
        causation_id="revoke_claim_01",
        occurred_at="2026-08-23T10:00:01Z",
        reason="owner-removed",
    )
    assert ClaimEventPage(next_stream_position=7, events=(event,)).events == (event,)
    with pytest.raises(ValidationError, match="checkpoint"):
        ClaimEventPage(next_stream_position=6, events=(event,))
