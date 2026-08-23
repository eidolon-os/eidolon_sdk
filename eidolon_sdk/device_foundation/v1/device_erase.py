"""Canonical device-local erase operation and ES256 acknowledgement helpers."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from typing import Literal

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .lifecycle import DeviceRef


class DeviceEraseContractError(ValueError):
    """The operation is malformed, conflicts, or has an invalid signature."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _wire_datetime(value: object) -> object:
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _aware(value: object) -> datetime:
    value = _wire_datetime(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return value.astimezone(UTC)


def _b64url_decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:  # noqa: BLE001 - normalized contract error
        raise DeviceEraseContractError("invalid base64url value") from exc


def canonical_bytes(value: BaseModel | dict[str, object]) -> bytes:
    document = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    try:
        return rfc8785.dumps(document)
    except (TypeError, ValueError) as exc:
        raise DeviceEraseContractError("operation is not RFC 8785 canonicalizable") from exc


class DeviceOperationKeyProof(_Model):
    device_instance_id: str = Field(min_length=3, max_length=128)
    enrollment_request_id: str = Field(min_length=3, max_length=128)
    public_key_spki: str = Field(min_length=120, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    possession_signature: str = Field(min_length=86, max_length=86, pattern=r"^[A-Za-z0-9_-]+$")

    def signing_document(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"possession_signature"})


class DeviceLocalErasePayload(_Model):
    erase_scopes: tuple[
        Literal["owner-credentials", "owner-data", "network-profiles"], ...
    ] = (
        "owner-credentials",
        "owner-data",
        "network-profiles",
    )

    @field_validator("erase_scopes", mode="before")
    @classmethod
    def _tuple(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def _unique_nonempty(self) -> DeviceLocalErasePayload:
        if not self.erase_scopes or len(set(self.erase_scopes)) != len(self.erase_scopes):
            raise ValueError("erase_scopes must be non-empty and unique")
        return self


class DeviceLocalEraseCommand(_Model):
    contract: Literal["eidolon.device-foundation.device-operation"] = (
        "eidolon.device-foundation.device-operation"
    )
    contract_version: Literal["1.0"] = "1.0"
    operation_id: str = Field(min_length=3, max_length=128)
    operation_type: Literal["device-local.erase"] = "device-local.erase"
    device_ref: DeviceRef
    deadline: datetime
    payload: DeviceLocalErasePayload = Field(default_factory=DeviceLocalErasePayload)

    @field_validator("deadline", mode="before")
    @classmethod
    def _deadline(cls, value: object) -> datetime:
        return _aware(value)


class DeviceLocalEraseAck(_Model):
    contract: Literal["eidolon.device-foundation.device-operation-ack"] = (
        "eidolon.device-foundation.device-operation-ack"
    )
    contract_version: Literal["1.0"] = "1.0"
    operation_id: str = Field(min_length=3, max_length=128)
    operation_type: Literal["device-local.erase"] = "device-local.erase"
    device_ref: DeviceRef
    ack_sequence: int = Field(ge=1)
    result: Literal["erased", "permanent-failure"]
    result_code: str = Field(min_length=1, max_length=128)
    device_monotonic_time: int = Field(ge=0)
    device_signature: str = Field(min_length=86, max_length=86, pattern=r"^[A-Za-z0-9_-]+$")

    def signing_document(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"device_signature"})


class DeviceLocalEraseOperationStatus(_Model):
    contract: Literal["eidolon.device-foundation.device-operation-status"] = (
        "eidolon.device-foundation.device-operation-status"
    )
    contract_version: Literal["1.0"] = "1.0"
    operation_id: str = Field(min_length=3, max_length=128)
    operation_type: Literal["device-local.erase"] = "device-local.erase"
    request_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    device_ref: DeviceRef
    created_at: datetime
    deadline: datetime
    state: Literal[
        "accepted",
        "pending",
        "delivery-accepted",
        "acknowledged",
        "expired",
        "permanent-failure",
    ]
    attempt_count: int = Field(ge=0)
    terminal_result: Literal["erased", "permanent-failure", "deadline-expired"] | None

    @field_validator("created_at", "deadline", mode="before")
    @classmethod
    def _timestamps(cls, value: object) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def _terminal_coherence(self) -> DeviceLocalEraseOperationStatus:
        expected_result = {
            "acknowledged": "erased",
            "expired": "deadline-expired",
            "permanent-failure": "permanent-failure",
        }.get(self.state)
        if self.terminal_result != expected_result:
            raise ValueError("terminal state and terminal_result disagree")
        if self.deadline <= self.created_at:
            raise ValueError("deadline must follow created_at")
        return self


def operation_fingerprint(command: DeviceLocalEraseCommand) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(command)).hexdigest()


def operation_key_id(public_key_spki: str) -> str:
    return "sha256:" + hashlib.sha256(_b64url_decode(public_key_spki)).hexdigest()


def verify_p256_signature(
    *, public_key_spki: str, signing_document: dict[str, object], signature: str
) -> None:
    try:
        key = serialization.load_der_public_key(_b64url_decode(public_key_spki))
    except (TypeError, ValueError) as exc:
        raise DeviceEraseContractError("invalid operational P-256 public key") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise DeviceEraseContractError("operational key is not P-256")
    raw = _b64url_decode(signature)
    if len(raw) != 64:
        raise DeviceEraseContractError("ES256 signature must be 64-byte R||S")
    der = encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )
    try:
        key.verify(der, canonical_bytes(signing_document), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise DeviceEraseContractError("device signature verification failed") from exc


def verify_operation_key_proof(proof: DeviceOperationKeyProof) -> None:
    verify_p256_signature(
        public_key_spki=proof.public_key_spki,
        signing_document=proof.signing_document(),
        signature=proof.possession_signature,
    )


def verify_device_erase_ack(*, ack: DeviceLocalEraseAck, public_key_spki: str) -> None:
    verify_p256_signature(
        public_key_spki=public_key_spki,
        signing_document=ack.signing_document(),
        signature=ack.device_signature,
    )
