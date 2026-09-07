"""Canonical Python bindings for exact-generation device removal."""

from __future__ import annotations

import hashlib
from base64 import urlsafe_b64decode
from binascii import Error as BinasciiError
from datetime import UTC, datetime
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal

import rfc8785
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    RootModel,
    field_validator,
    model_validator,
)
from pydantic_core import core_schema


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class WireEnum(StrEnum):
    """A canonical enum that accepts the wire form it is written as.

    These models are strict on purpose: it is what stops a producer sending
    ``"1"`` where an integer belongs. But an enum's wire form *is* a string, and
    strict Python-mode validation rejected it — so a model could be parsed from
    a JSON document and never from the dictionary that same document decodes to.

    That is not a distinction a wire contract can afford. It held everywhere a
    canonical DTO crossed a process boundary as a decoded body rather than as
    bytes, which is what every ASGI framework hands a handler: the Host's own
    control plane answered 422 to its own Local API, and reading the pending
    device queue failed on the Host while every test passed.

    The rule this restores is one line: a canonical model validates its own
    ``model_dump(mode="json")``. An unrecognised string is still refused.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_before_validator_function(
            cls._accept_wire_value, handler(source)
        )

    @classmethod
    def _accept_wire_value(cls, value: object) -> object:
        if isinstance(value, cls) or not isinstance(value, str):
            return value
        try:
            return cls(value)
        except ValueError:
            return value


def _wire_datetime(value: object) -> object:
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _aware_datetime(value: object) -> datetime:
    value = _wire_datetime(value)
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return value.astimezone(UTC)


_DEVICE_INSTANCE_ID_PATTERN = r"^device-instance-[0-9a-f]{64}$"
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"


class OwnerDomainId(RootModel[str]):
    """Nominal Owner Sovereign Domain identifier; never a tenant/account id."""

    model_config = ConfigDict(frozen=True, strict=True)

    @field_validator("root")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not 3 <= len(value) <= 128 or not value.startswith("owner-"):
            raise ValueError("OwnerDomainId must use the owner- namespace")
        return value

    def __str__(self) -> str:
        return self.root


class BusinessOwnerId(RootModel[str]):
    """Nominal business Owner/tenant identifier; never an Owner Domain id."""

    model_config = ConfigDict(frozen=True, strict=True)

    @field_validator("root")
    @classmethod
    def _valid(cls, value: str) -> str:
        if not 3 <= len(value) <= 128 or not value.startswith("owner_"):
            raise ValueError("BusinessOwnerId must use the owner_ namespace")
        return value

    def __str__(self) -> str:
        return self.root


#: How a device's instance identity is derived from its own operational key.
#:
#: The rule existed in four places and was written down in none: Hub enforced it
#: in one local expression and answered 422 to anything else, the firmware built
#: the same string by hand and happened to agree, a phone invented
#: ``mobile-android-<hash>`` and compared unequal forever instead of being
#: refused, and the contract typed the field as a loose Identifier so no client
#: could have known. It lives here now, once, and the schema names the shape so
#: an invented id fails at the boundary rather than at Hub.
DEVICE_INSTANCE_NAMESPACE = "device-instance-"


#: How an operational public key declares itself on the wire. Stripped here
#: rather than by each caller, because "which bytes get hashed" is the whole
#: content of the rule below: a caller that strips it itself and a caller that
#: forgets to would derive two different identities for one key.
SPKI_SCHEME = "p256-spki:"

#: The 26-byte header of every P-256 SubjectPublicKeyInfo: SEQUENCE,
#: AlgorithmIdentifier { id-ecPublicKey, prime256v1 }, then the BIT STRING that
#: carries the 65-byte uncompressed point.
P256_SPKI_PREFIX = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")

#: `0x04 || X || Y` — the same key an SPKI carries, written without its header.
P256_UNCOMPRESSED_POINT_LENGTH = 65


def operational_public_key_bytes(operational_public_key: str) -> bytes:
    """The bytes a wire public key stands for, whether or not it names its scheme.

    Both spellings occur in the contract — enrollment carries
    ``p256-spki:<base64url>`` while the erase vectors carry the bare base64url
    SPKI — and they must mean the same key, so one function reads both. Anything
    else is refused rather than hashed as-is.
    """

    encoded = operational_public_key.removeprefix(SPKI_SCHEME)
    try:
        raw = urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (BinasciiError, ValueError) as exc:
        raise ValueError("operational public key is not base64url SPKI") from exc
    if not raw:
        raise ValueError("operational public key is empty")
    if raw[:1] == b"\x04" and len(raw) == P256_UNCOMPRESSED_POINT_LENGTH:
        # The same key, written the other way — and the difference disappears
        # the moment it is hashed. Both encodings name one P-256 key, but their
        # digests are two different, equally well-formed device instance ids,
        # and an Authority knows only one of them. Accepting this quietly is
        # worse than refusing it: nothing fails at the point of the mistake, and
        # what surfaces later is a device nobody has a record of.
        raise ValueError(
            "operational public key is a raw uncompressed point, not SPKI: "
            "hashing it would derive an identity no Authority has a record of"
        )
    if len(raw) != len(P256_SPKI_PREFIX) + P256_UNCOMPRESSED_POINT_LENGTH or not raw.startswith(
        P256_SPKI_PREFIX
    ):
        raise ValueError("operational public key is not a P-256 SubjectPublicKeyInfo")
    return raw


def operational_key_id(operational_public_key: str) -> str:
    """The ``sha256:<hex>`` fingerprint of an operational key's SPKI bytes.

    One value with several jobs: the ``operational_spki_sha256`` a commissioning
    voucher is bound to, the digest a ``device_instance_id`` is derived from,
    and the key id the erase ledger records. Every one of them is compared for
    equality against a value some other process computed, so two spellings of
    this are two identities for one key — and the mismatch is never reported as
    a fingerprint disagreement, only as a device nobody has a record of.

    It went wrong once already in the direction the helper above guards: the
    erase ledger's ``p256-spki:`` spelling reached a decoder that knew only the
    bare base64url, and every ACK a real Body signed was refused as an invalid
    key. So this reads the SPKI through the one function that accepts both
    spellings and refuses everything else, rather than hashing whatever arrived.
    """

    digest = hashlib.sha256(operational_public_key_bytes(operational_public_key))
    return "sha256:" + digest.hexdigest()


def derive_device_instance_id(operational_public_key: str) -> str:
    """The device instance id that key, and only that key, may claim.

    Takes the key as it appears on the wire, not a pre-hashed digest: a caller
    that hashes it itself is a second implementation of the same rule. There
    were three — Hub built the string from its own ``key_id``, the firmware
    concatenated its own hex, and the contract said only "some identifier", so
    the vectors said a device's identity was its MAC address.
    """

    return DEVICE_INSTANCE_NAMESPACE + hashlib.sha256(
        operational_public_key_bytes(operational_public_key)
    ).hexdigest()


#: A device instance identity, which is a statement about a key rather than a
#: name anything may choose.
#:
#: Deliberately a constrained ``str`` and not a wrapper type: this value is
#: compared against strings from the wire, from SQL rows and from LiveKit room
#: names in well over a hundred places, and a wrapper would have turned every
#: one of those comparisons silently false instead of loudly wrong.
DeviceInstanceId = Annotated[
    str,
    Field(min_length=80, max_length=80, pattern=_DEVICE_INSTANCE_ID_PATTERN),
]


class ManifestRef(_Model):
    manifest_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    revision: int = Field(ge=1)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def manifest_digest(document: Mapping[str, Any]) -> str:
    """The one definition of what a Manifest's digest is.

    Every producer and every reader of a Manifest was computing this by hand.
    They agreed, but only because nobody had written a second one down yet.
    """

    return "sha256:" + hashlib.sha256(rfc8785.dumps(dict(document))).hexdigest()


class _ManifestPart(BaseModel):
    """One entry inside a Manifest, exact like every other canonical document.

    ``populate_by_name``/``serialize_by_alias`` are here for ``schema``, which
    shadows an attribute on ``BaseModel`` and so cannot be a field name. Without
    the serialization alias the model could parse a wire document and then dump
    one no binding accepts.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class ManifestProperty(_ManifestPart):
    name: str = Field(min_length=1, max_length=128)
    schema_: dict[str, Any] = Field(alias="schema")
    observable: bool
    writable: bool


class ManifestAction(_ManifestPart):
    name: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1, le=65_535)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    idempotent: bool


class ManifestEvent(_ManifestPart):
    name: str = Field(min_length=1, max_length=128)
    data_schema: dict[str, Any]


class ManifestMedia(_ManifestPart):
    """What a Body can carry, and which way.

    ``kind`` and ``direction`` decide the device's publish grants, so a media
    entry that omits either is asking for a permission without saying which.
    ``codecs`` is optional: no consumer anywhere reads a codec value, and the
    values shipped by working producers already disagree — a board sends
    ``opus`` where a fixture says ``audio/opus`` and both are carried. It was
    the only field in this document able to refuse a device, with no reader to
    justify the refusal.
    """

    kind: Literal["audio", "video"]
    direction: Literal["publish", "subscribe", "bidirectional"]
    codecs: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("codecs", mode="before")
    @classmethod
    def _codecs(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class DeviceCapabilityManifest(_ManifestPart):
    """The shape of a device's declaration — its vocabulary, and nothing more.

    The field set, ``kind`` and ``direction`` are vocabulary facts. Checking
    them requires knowing nothing about whether a Channel exists, whether this
    deployment runs a media transport, or whether this device should be given a
    conversational agent; all of that stays with the Channel Authority, which is
    the only reader of a Manifest's content.

    That distinction is the point. An Authority is deliberately opaque to what a
    Manifest *means*: requiring this vocabulary's own version field of a
    document authored elsewhere is what let one projection row crash-loop a Hub
    at boot, for a Manifest it had already accepted. But "not the Authority's
    semantics" was taken to mean "not checked anywhere", and the entry typed the
    document ``{"type": "object"}``. A wrong shape was therefore accepted,
    approved by an Owner — an approval that cannot be un-spent — forwarded, and
    only then refused by the Provider, which the Authority recorded as a channel
    still pending. Nothing was wrong with the device that waiting would fix.

    This runs at the wire boundary, on a document being proposed. It is not on
    the path that hydrates stored documents, so a Manifest already accepted
    under the older, wider entry still projects and still boots.
    """

    schema_version: Literal[1]
    title: str = Field(min_length=1, max_length=128)
    properties: tuple[ManifestProperty, ...] = Field(max_length=64)
    actions: tuple[ManifestAction, ...] = Field(max_length=64)
    events: tuple[ManifestEvent, ...] = Field(max_length=64)
    media: tuple[ManifestMedia, ...] = Field(max_length=16)

    @field_validator("properties", "actions", "events", "media", mode="before")
    @classmethod
    def _arrays(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("title", mode="after")
    @classmethod
    def _title_says_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("manifest title cannot be blank")
        return value


class ManifestDocument(_Model):
    """A device's own account of what it can do, as of some revision of itself.

    ``revision`` is the *device's* count of how many times its capabilities have
    changed, not a digest and not an Authority's version. It exists so that a
    replayed or reordered assertion cannot quietly reinstate an older account of
    a device that has since been upgraded.
    """

    manifest_id: str = Field(min_length=3, max_length=128)
    revision: int = Field(ge=1)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    #: Kept as the decoded object the device sent, not as the parsed model: the
    #: digest is over exactly these bytes, and normalising the document through
    #: a binding would make the two disagree for anything the binding tidied.
    document: dict[str, Any]

    @field_validator("document", mode="after")
    @classmethod
    def _document_declares_the_canonical_shape(cls, value: dict[str, Any]) -> dict[str, Any]:
        DeviceCapabilityManifest.model_validate(value)
        return value

    @model_validator(mode="after")
    def _digest_describes_this_document(self) -> "ManifestDocument":
        if self.digest != manifest_digest(self.document):
            raise ValueError("manifest digest does not describe its document")
        return self

    @property
    def ref(self) -> ManifestRef:
        return ManifestRef(
            manifest_id=self.manifest_id, revision=self.revision, digest=self.digest
        )


class DeviceRef(_Model):
    device_instance_id: DeviceInstanceId
    owner_domain_id: OwnerDomainId
    owner_domain_generation: int = Field(ge=1)
    claim_generation: int = Field(ge=1)
    trust_epoch: int = Field(ge=1)


class CommandEnvelope(_Model):
    contract: Literal["eidolon.device-foundation.command"] = "eidolon.device-foundation.command"
    contract_version: Literal["1.0"] = "1.0"
    command_type: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    correlation_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    causation_id: str | None = Field(default=None, min_length=3, max_length=128)
    issued_at: datetime
    deadline: datetime | None
    payload: dict[str, object]
    extensions: dict[str, object]

    @field_validator("issued_at", "deadline", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime | None:
        return None if value is None else _aware_datetime(value)


class CommandResult(_Model):
    command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    outcome: Literal["committed", "replayed", "accepted"]
    resource_ref: dict[str, object]
    resource_revision: int | None = Field(default=None, ge=0)
    occurred_at: datetime
    extensions: dict[str, object]

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _time(cls, value: object) -> datetime:
        return _aware_datetime(value)


class DeviceProblem(_Model):
    code: Literal[
        "INVALID_ARGUMENT", "CONTRACT_UNSUPPORTED", "UNAUTHENTICATED", "FORBIDDEN",
        "NOT_FOUND", "IDEMPOTENCY_CONFLICT", "REVISION_CONFLICT", "GENERATION_CONFLICT",
        "CURSOR_GAP",
        "CLAIM_REVOKED", "TRUST_EPOCH_STALE", "OWNER_DOMAIN_MISMATCH",
        "BUSINESS_OWNER_MISMATCH", "DECISION_REQUIRED", "HANDOFF_PROOF_INVALID",
        "GRANT_EXPIRED", "PROPOSAL_TERMINAL", "PROPOSAL_EXPIRED", "OPERATION_EXPIRED",
        "RATE_LIMITED", "AUTHORITY_UNAVAILABLE", "DELIVERY_UNAVAILABLE", "INTERNAL",
    ]
    category: Literal["invalid", "auth", "forbidden", "missing", "conflict", "expired", "unavailable", "internal"]
    retryable: bool
    authority: Literal["admission", "device-control", "body-mesh", "companion", "delivery"]
    command_id: str | None = None
    resource_ref: dict[str, object] | None
    current_revision: int | None = Field(default=None, ge=0)
    current_generation: int | None = Field(default=None, ge=0)
    retry_after_ms: int | None = Field(default=None, ge=1)
    detail: str = Field(max_length=1024)
    incident_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)

    @model_validator(mode="after")
    def _retry(self) -> DeviceProblem:
        if not self.retryable and self.retry_after_ms is not None:
            raise ValueError("non-retryable problem cannot carry retry_after_ms")
        if self.code == "RATE_LIMITED" and (not self.retryable or self.retry_after_ms is None):
            raise ValueError("RATE_LIMITED must be retryable with retry_after_ms")
        return self


class ActorRef(_Model):
    principal_id: str = Field(
        min_length=3, max_length=128, pattern=_IDENTIFIER
    )
    principal_type: Literal["controller", "device", "service", "operator"]
    owner_domain_id: OwnerDomainId | None = None
    granted_scopes: tuple[str, ...] = Field(min_length=1)
    authentication_strength: Literal[
        "software", "hardware-backed", "physical-presence"
    ]

    @field_validator("granted_scopes", mode="before")
    @classmethod
    def _unique_scopes(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            value = tuple(value)
        if not isinstance(value, tuple):
            raise ValueError("granted_scopes must be an array")
        if len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("granted_scopes must be unique and non-empty")
        return value


class OwnerAuthorizationContext(_Model):
    workload_principal_id: str = Field(
        min_length=3, max_length=128, pattern=_IDENTIFIER
    )
    actor: ActorRef
    authorized_owner_domain_id: OwnerDomainId
    audience: Literal["eidolon-admission"] = "eidolon-admission"
    scopes: tuple[Literal["device.read", "device.claim.revoke"], ...] = Field(
        min_length=1
    )
    intent_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    target_device_ref: DeviceRef
    issued_at: datetime
    expires_at: datetime

    @field_validator("scopes", mode="before")
    @classmethod
    def _scope_array(cls, value: object) -> object:
        value = tuple(value) if isinstance(value, list) else value
        if isinstance(value, tuple) and len(value) != len(set(value)):
            raise ValueError("authorization scopes must be unique")
        return value

    @field_validator("issued_at", "expires_at", mode="before")
    @classmethod
    def _aware(cls, value: object) -> datetime:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _coherent(self) -> OwnerAuthorizationContext:
        if self.expires_at <= self.issued_at:
            raise ValueError("authorization expires_at must follow issued_at")
        if self.authorized_owner_domain_id != self.target_device_ref.owner_domain_id:
            raise ValueError("authorization Owner and target DeviceRef do not match")
        if self.actor.owner_domain_id not in {None, self.authorized_owner_domain_id}:
            raise ValueError("actor Owner and authorized Owner do not match")
        if "device.claim.revoke" not in self.scopes:
            raise ValueError("removal authorization requires device.claim.revoke")
        if not set(self.scopes).issubset(self.actor.granted_scopes):
            raise ValueError("authorization scopes exceed the ActorRef grant")
        return self


class RemovalIntent(_Model):
    intent_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    ingress_request_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    device_ref: DeviceRef
    actor: ActorRef
    reason: str = Field(min_length=1, max_length=256)
    claim_command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    state: Literal["accepted", "claim-revoked", "converged", "blocked"]
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _timestamps(cls, value: object) -> object:
        return _aware_datetime(value)

    @model_validator(mode="after")
    def _coherent(self) -> RemovalIntent:
        if self.updated_at < self.created_at:
            raise ValueError("RemovalIntent updated_at precedes created_at")
        if self.actor.owner_domain_id not in {None, self.device_ref.owner_domain_id}:
            raise ValueError("RemovalIntent actor Owner and DeviceRef do not match")
        return self


class RevokeClaim(_Model):
    operation: Literal["device.claim-revocation"] = "device.claim-revocation"
    command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    correlation_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    device_ref: DeviceRef
    reason: str = Field(min_length=1, max_length=256)


class RevokeClaimResult(_Model):
    operation: Literal["device.claim-revocation-result"] = (
        "device.claim-revocation-result"
    )
    command_id: str = Field(min_length=3, max_length=128, pattern=_IDENTIFIER)
    outcome: Literal["committed", "replayed"]
    device_ref: DeviceRef
    aggregate_revision: int = Field(ge=1)
    occurred_at: datetime
    event_id: str | None = Field(default=None, min_length=3, max_length=128)
    lifecycle_state: Literal["revoked"] = "revoked"

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _occurred_at(cls, value: object) -> object:
        return _aware_datetime(value)


def revoke_claim_fingerprint(command: RevokeClaim) -> str:
    """Fingerprint one semantic revoke mutation, excluding retry/audit metadata."""

    document = {
        "command_type": "device.claim.revoke",
        "owner_domain_id": str(command.device_ref.owner_domain_id),
        "payload": {
            "device_ref": command.device_ref.model_dump(mode="json"),
            "reason": command.reason,
        },
    }
    return "sha256:" + hashlib.sha256(rfc8785.dumps(document)).hexdigest()
