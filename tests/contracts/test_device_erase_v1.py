from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from pydantic import ValidationError

from eidolon_sdk.device_foundation.v1 import (
    DeviceEraseContractError,
    DeviceLocalEraseAck,
    DeviceLocalEraseCommand,
    DeviceLocalEraseOperationStatus,
    DeviceOperationKeyProof,
    DeviceRef,
    canonical_bytes,
    operation_fingerprint,
    operation_key_id,
    verify_device_erase_ack,
    verify_operation_key_proof,
)
from eidolon_sdk.device_foundation.v1.lifecycle import SPKI_SCHEME
from eidolon_sdk.device_foundation.v1.testing import named_device_instance_id


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _raw_sign(key: ec.EllipticCurvePrivateKey, document: dict[str, object]) -> str:
    der = key.sign(canonical_bytes(document), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


_DEVICE = named_device_instance_id("device-under-test")


def _ref(*, generation: int = 7) -> DeviceRef:
    return DeviceRef(
        device_instance_id=_DEVICE,
        owner_domain_id="owner-domain_01",
        owner_domain_generation=3,
        claim_generation=generation,
        trust_epoch=4,
    )


def _command(*, generation: int = 7, deadline: datetime | None = None):
    return DeviceLocalEraseCommand(
        operation_id="erase_operation_01",
        device_ref=_ref(generation=generation),
        deadline=deadline or datetime(2026, 8, 30, tzinfo=UTC),
    )


def test_operation_fingerprint_is_stable_and_generation_deadline_bound() -> None:
    command = _command()
    assert operation_fingerprint(command) == operation_fingerprint(
        DeviceLocalEraseCommand.model_validate(command.model_dump(mode="json"))
    )
    assert operation_fingerprint(command) != operation_fingerprint(_command(generation=8))
    assert operation_fingerprint(command) != operation_fingerprint(
        _command(deadline=command.deadline + timedelta(days=1))
    )


def test_key_proof_and_ack_require_the_bound_device_private_key() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    other = ec.generate_private_key(ec.SECP256R1())
    spki = _b64(
        key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    proof_values = {
        "device_instance_id": _DEVICE,
        "enrollment_request_id": "enrollment_request_01",
        "public_key_spki": spki,
    }
    proof = DeviceOperationKeyProof(
        **proof_values,
        possession_signature=_raw_sign(key, proof_values),
    )
    verify_operation_key_proof(proof)

    ack_values = {
        "contract": "eidolon.device-foundation.device-operation-ack",
        "contract_version": "1.0",
        "operation_id": "erase_operation_01",
        "operation_type": "device-local.erase",
        "device_ref": _ref().model_dump(mode="json"),
        "ack_sequence": 1,
        "result": "erased",
        "result_code": "ERASED",
        "device_monotonic_time": 1234,
    }
    ack = DeviceLocalEraseAck(
        **ack_values,
        device_signature=_raw_sign(key, ack_values),
    )
    verify_device_erase_ack(ack=ack, public_key_spki=spki)

    bad = ack.model_copy(
        update={"device_signature": _raw_sign(other, ack.signing_document())}
    )
    with pytest.raises(DeviceEraseContractError, match="verification failed"):
        verify_device_erase_ack(ack=bad, public_key_spki=spki)

    # The same key as the erase ledger records it. A device hands up the bare
    # base64url SPKI, but the operation is bound to the key admission stored,
    # which names its scheme — and that recorded spelling is what arrives here.
    # Reading only the bare form refused every ACK a real Body ever signed.
    scheme_named = SPKI_SCHEME + spki
    verify_device_erase_ack(ack=ack, public_key_spki=scheme_named)
    assert operation_key_id(scheme_named) == operation_key_id(spki)
    with pytest.raises(DeviceEraseContractError, match="verification failed"):
        verify_device_erase_ack(ack=bad, public_key_spki=scheme_named)


def test_status_cannot_report_acknowledged_without_terminal_result() -> None:
    values = {
        "operation_id": "erase_operation_01",
        "request_fingerprint": "sha256:" + "b" * 64,
        "device_ref": _ref(),
        "created_at": datetime(2026, 8, 23, tzinfo=UTC),
        "deadline": datetime(2026, 8, 30, tzinfo=UTC),
        "state": "acknowledged",
        "attempt_count": 1,
        "terminal_result": None,
    }
    with pytest.raises(ValidationError, match="terminal state"):
        DeviceLocalEraseOperationStatus(**values)

    with pytest.raises(ValidationError, match="terminal state"):
        DeviceLocalEraseOperationStatus(
            **{**values, "terminal_result": "permanent-failure"}
        )
