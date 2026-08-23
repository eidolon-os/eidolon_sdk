from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from eidolon_sdk.device_foundation.v1 import (
    ActorRef,
    DeviceRef,
    OwnerAuthorizationContext,
    RemovalIntent,
    RevokeClaim,
)


def _ref(*, owner: str = "owner_01", generation: int = 2) -> DeviceRef:
    return DeviceRef(
        device_instance_id="device_01",
        owner_domain_id=owner,
        claim_generation=generation,
        trust_epoch=4,
        accepted_manifest_digest="sha256:" + "2" * 64,
    )


def test_device_ref_accepts_deployed_mac_style_instance_id() -> None:
    ref = DeviceRef(
        device_instance_id="10:51:db:7e:24:44",
        owner_domain_id="owner_01",
        claim_generation=2,
        trust_epoch=4,
        accepted_manifest_digest="sha256:" + "2" * 64,
    )

    assert ref.device_instance_id == "10:51:db:7e:24:44"


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
            owner_domain_id="owner_01",
            granted_scopes=("device.claim.revoke",),
            authentication_strength="hardware-backed",
        ),
        "authorized_owner_domain_id": "owner_01",
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
            **{**values, "target_device_ref": _ref(owner="owner_02")}
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
            owner_domain_id="owner_01",
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
