"""The credential an Admission mutation is presented with.

Admin mints these and Hub reads them. Both are Python and both already import
this package, so this is one implementation rather than two that agree — there
is no second copy to drift, and nothing to compare.

That is not how it started. Admin built the claim dictionary by hand with
PyJWT, Hub took it apart by hand with python-jose, and the claim set existed
only as those two hand-written lists. They diverged: the removal path minted
``actor_ref`` as a bare string, ``owner_id`` instead of ``owner_domain_id``,
and no ``business_owner_id`` at all — the vocabulary of a different Hub surface
— and presented it here. Hub read ``claims["actor"]``, raised ``KeyError``
inside its own broad ``except``, and answered 401 "invalid Admission
credential". Every device removal anyone attempted was refused by that, for
months, and the refusal never mentioned a credential.

The invariants below are the reason a shared definition beats a shared test:
they are checked when the credential is built and again when it is read, so a
credential that cannot be true cannot be minted in the first place.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .admission import BusinessOwnerId, ControllerActorRef, OwnerDomainId
from .lifecycle import DeviceRef

#: The audience every Admission credential is minted for and read against.
#: One constant, because "which surface is this for" is exactly the fact that
#: went wrong when each side spelled it out separately.
ADMISSION_AUDIENCE = "eidolon-admission"

_ALGORITHM = "HS256"
_MINIMUM_SECRET_BYTES = 32


class AdmissionCredentialError(ValueError):
    """A credential could not be minted or could not be trusted."""


class AdmissionCredential(BaseModel):
    """What an Admission credential says, and what it may not say."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject: str = Field(min_length=3, max_length=128)
    actor: ControllerActorRef
    owner_domain_id: OwnerDomainId
    business_owner_id: BusinessOwnerId
    scopes: tuple[str, ...] = Field(min_length=1, max_length=16)
    intent_id: str | None = Field(default=None, max_length=128)
    #: The one device this credential authorizes an operation against.
    #:
    #: Optional because not every Admission mutation has one — deciding an
    #: Enrollment names an Enrollment, not a Device. A surface that fences on
    #: the exact generation refuses a credential without it, rather than
    #: treating "not fenced" as "fenced to whatever arrived".
    target_device_ref: DeviceRef | None = None

    @model_validator(mode="after")
    def _cannot_say_two_things_about_one_fact(self) -> "AdmissionCredential":
        if self.actor.owner_domain_id != self.owner_domain_id:
            raise ValueError("credential actor belongs to another Owner Domain")
        if set(self.scopes) != set(self.actor.granted_scopes):
            raise ValueError("credential scopes and the actor's granted scopes differ")
        return self


def issue_admission_credential(
    credential: AdmissionCredential,
    *,
    secret: bytes,
    ttl_seconds: int,
    now: datetime | None = None,
) -> str:
    """Mint one short-lived credential, returned as a complete header value.

    The ``Bearer `` prefix is part of what is returned because it is part of
    what is presented: a caller that has to remember to add it is a caller that
    can forget.
    """

    if len(secret) < _MINIMUM_SECRET_BYTES:
        raise AdmissionCredentialError(
            f"Admission credential secret must contain at least {_MINIMUM_SECRET_BYTES} bytes"
        )
    if ttl_seconds <= 0:
        raise AdmissionCredentialError("Admission credential lifetime must be positive")
    issued_at = now or datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": credential.subject,
        # The presenter is the subject. Carried rather than implied so a reader
        # can refuse a credential that was minted for one party and presented
        # by another without having to know who either of them is.
        "presenter": credential.subject,
        "aud": ADMISSION_AUDIENCE,
        "actor": credential.actor.model_dump(mode="json"),
        "owner_domain_id": str(credential.owner_domain_id),
        "business_owner_id": str(credential.business_owner_id),
        "scopes": list(credential.scopes),
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    if credential.intent_id is not None:
        claims["intent_id"] = credential.intent_id
    if credential.target_device_ref is not None:
        claims["target_device_ref"] = credential.target_device_ref.model_dump(mode="json")
    return "Bearer " + jwt.encode(claims, secret, algorithm=_ALGORITHM)


def read_admission_credential(header: str, *, secret: bytes) -> AdmissionCredential:
    """Read a presented header, or refuse it. Never returns something half-true."""

    if len(secret) < _MINIMUM_SECRET_BYTES:
        raise AdmissionCredentialError(
            f"Admission credential secret must contain at least {_MINIMUM_SECRET_BYTES} bytes"
        )
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise AdmissionCredentialError("Bearer Admission credential required")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            audience=ADMISSION_AUDIENCE,
            options={"require": ["sub", "exp", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise AdmissionCredentialError("invalid Admission credential") from exc
    subject = str(claims.get("sub") or "").strip()
    if not subject or str(claims.get("presenter") or "").strip() != subject:
        raise AdmissionCredentialError("Admission presenter is not bound to the subject")
    try:
        return AdmissionCredential(
            subject=subject,
            actor=ControllerActorRef.model_validate(claims["actor"]),
            owner_domain_id=OwnerDomainId(claims["owner_domain_id"]),
            business_owner_id=BusinessOwnerId(claims["business_owner_id"]),
            scopes=tuple(str(item) for item in claims.get("scopes", ())),
            intent_id=(
                str(claims["intent_id"]) if claims.get("intent_id") is not None else None
            ),
            target_device_ref=(
                DeviceRef.model_validate(claims["target_device_ref"])
                if claims.get("target_device_ref") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AdmissionCredentialError("invalid Admission credential") from exc
