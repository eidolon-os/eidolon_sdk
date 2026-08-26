from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jwt
import pytest

from eidolon_sdk.device_foundation.v1 import (
    ADMISSION_AUDIENCE,
    AdmissionCredential,
    AdmissionCredentialError,
    BusinessOwnerId,
    ControllerActorRef,
    OwnerDomainId,
    issue_admission_credential,
    read_admission_credential,
)

GOLDEN = (
    Path(__file__).resolve().parents[2]
    / "contracts/device_foundation/v1/golden/admission-credential.json"
)
SECRET = b"admission-owner-secret-value-0001"
NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _claims(token: str) -> dict:
    return jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False, "verify_aud": False},
    )


def _recent() -> int:
    return int(datetime.now(UTC).timestamp()) - 1


def _soon() -> int:
    return int(datetime.now(UTC).timestamp()) + 300


def _credential(**overrides) -> AdmissionCredential:
    domain = OwnerDomainId("owner-b0a862b0aab941d64554")
    values = {
        "subject": "eidolon-admin/lifecycle-workflow",
        "actor": ControllerActorRef(
            principal_id="ectrl-338e747461a3ecd0abbd",
            owner_domain_id=domain,
            granted_scopes=("device.claim.revoke",),
            authentication_strength="software",
        ),
        "owner_domain_id": domain,
        "business_owner_id": BusinessOwnerId("owner_683f963f54885e868924"),
        "scopes": ("device.claim.revoke",),
        "intent_id": "removal-intent-" + "a" * 32,
    }
    values.update(overrides)
    return AdmissionCredential(**values)


def test_the_golden_names_every_claim_this_credential_carries() -> None:
    """One definition, and a golden so a future non-Python reader has one too.

    Admin used to build these claims by hand with PyJWT and Hub took them apart
    by hand with python-jose. The two lists diverged and every device removal
    was answered 401 for months.
    """

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    header = issue_admission_credential(
        _credential(), secret=SECRET, ttl_seconds=60, now=NOW
    )
    scheme, _, token = header.partition(" ")
    claims = _claims(token)

    assert scheme == golden["header_scheme"]
    # Names for everything, values only for what does not depend on when it was
    # minted. Pinning a timestamp makes a test pass or fail by the wall clock,
    # which says nothing about the code.
    assert set(claims) == set(golden["required_claims"]) | set(golden["optional_claims"])
    assert {key: claims[key] for key in golden["stable_claims"]} == golden["stable_claims"]


def test_a_credential_that_reads_back_differently_is_not_the_one_that_was_minted() -> None:
    minted = _credential()

    # The real clock here on purpose: a credential is only readable while it is
    # live, and a fixed instant makes this pass or fail by the calendar.
    read = read_admission_credential(
        issue_admission_credential(minted, secret=SECRET, ttl_seconds=60),
        secret=SECRET,
    )

    assert read == minted


@pytest.mark.parametrize(
    "claim",
    ["sub", "presenter", "actor", "owner_domain_id", "business_owner_id", "exp", "aud"],
)
def test_a_credential_missing_any_claim_is_refused(claim: str) -> None:
    """Half a credential must not read back as a whole one."""

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    whole = dict(golden["stable_claims"], iat=_recent(), exp=_soon())
    without = {key: value for key, value in whole.items() if key != claim}
    token = jwt.encode(without, SECRET, algorithm="HS256")

    with pytest.raises(AdmissionCredentialError):
        read_admission_credential(f"Bearer {token}", secret=SECRET)


def test_the_other_surface_s_vocabulary_is_refused_here() -> None:
    """The exact shape that produced the 401, pinned as a refusal.

    ``actor_ref`` as a bare string, ``owner_id`` instead of ``owner_domain_id``,
    no ``business_owner_id``: correct for Hub's device-management surface and
    wrong for this one.
    """

    token = jwt.encode(
        {
            "sub": "eidolon-admin/lifecycle-workflow",
            "presenter": "eidolon-admin/lifecycle-workflow",
            "aud": ADMISSION_AUDIENCE,
            "actor_ref": "controller:ectrl-338e747461a3ecd0abbd",
            "owner_id": "owner-b0a862b0aab941d64554",
            "roles": ["device-manager"],
            "scopes": ["device.claim.revoke"],
            "exp": 4_000_000_000,
        },
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(AdmissionCredentialError):
        read_admission_credential(f"Bearer {token}", secret=SECRET)


def test_a_credential_cannot_claim_two_things_about_one_fact() -> None:
    """Checked when built, so an untrue credential is never minted at all."""

    other = OwnerDomainId("owner-000000000000000000ff")

    with pytest.raises(ValueError, match="another Owner Domain"):
        _credential(owner_domain_id=other)

    with pytest.raises(ValueError, match="scopes"):
        _credential(scopes=("device.read",))


def test_a_secret_too_short_to_sign_with_is_refused_on_both_sides() -> None:
    with pytest.raises(AdmissionCredentialError):
        issue_admission_credential(_credential(), secret=b"short", ttl_seconds=60)
    with pytest.raises(AdmissionCredentialError):
        read_admission_credential("Bearer x", secret=b"short")


def test_a_header_that_is_not_a_bearer_header_is_refused() -> None:
    for header in ("", "x", "Basic abc", "Bearer"):
        with pytest.raises(AdmissionCredentialError):
            read_admission_credential(header, secret=SECRET)


def test_an_expired_credential_is_refused() -> None:
    """Short-lived means short-lived, not "was valid once"."""

    header = issue_admission_credential(
        _credential(),
        secret=SECRET,
        ttl_seconds=1,
        now=datetime.now(UTC).replace(year=2020),
    )

    with pytest.raises(AdmissionCredentialError):
        read_admission_credential(header, secret=SECRET)


def test_a_credential_signed_with_another_secret_is_refused() -> None:
    header = issue_admission_credential(_credential(), secret=SECRET, ttl_seconds=60)

    with pytest.raises(AdmissionCredentialError):
        read_admission_credential(header, secret=b"another-secret-value-000000000001")
