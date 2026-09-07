#!/usr/bin/env python3
"""Executable P0 conformance runner for Device Foundation V1 source artifacts."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import jwt
import rfc8785
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
FORMAT_CHECKER = FormatChecker()
P256_ORDER = int("ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551", 16)


class ConformanceError(RuntimeError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConformanceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_reject_duplicate_keys)


def canonical_bytes(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (ValueError, TypeError) as exc:
        raise ConformanceError(f"value is not RFC 8785/I-JSON: {exc}") from exc


from eidolon_sdk.device_foundation.v1 import (  # noqa: E402
    ADMISSION_AUDIENCE,
    DEVICE_CONTROL_CONFIGURATION_OPERATION,
    MANIFEST_ASSERTION_OPERATION,
    AssertDeviceManifest,
    ManifestDocument,
    BASE_IDENTITY_EVIDENCE_FIELDS,
    BASE_IDENTITY_EVIDENCE_SCHEME,
    COMMISSIONING_VOUCHER_CLAIM_NAMES,
    COMMISSIONING_VOUCHER_HEADER,
    COMMISSIONING_VOUCHER_KEY_INFO,
    COMMISSIONING_VOUCHER_PURPOSE,
    claim_grant_ack_proof_document,
    base_identity_evidence_digest,
    base_identity_evidence_document,
    base_identity_evidence_wire,
    claim_grant_collection_proof_document,
    commissioning_voucher_claims,
    derive_voucher_signing_key,
    operational_key_id,
    sign_commissioning_voucher,
    device_control_configuration_proof_document,
    AdmissionCredential,
    AdmissionCredentialError,
    BusinessOwnerId,
    ControllerActorRef,
    DeviceCapabilityManifest,
    DeviceRef,
    OwnerDomainId,
    derive_device_instance_id,
    issue_admission_credential,
    manifest_digest,
    read_admission_credential,
)

_ALGORITHM_NAME = "HS256"


def _field_paths(value: Any, prefix: str = "", opaque: frozenset[str] = frozenset()) -> Any:
    """Every field position a golden vector actually contains, at any depth.

    Except under an `opaque` path. Some fields carry a *document* rather than a
    field set — the input side of a canonicalisation vector is the clearest
    case: its whole purpose is that arbitrary JSON canonicalises the same way,
    so a key added inside it is a new test input, not a new contract field.
    Enumerating into it would demand a declaration for every leaf of every
    payload and teach the reader to add names without thinking, which is the
    habit this whole mechanism exists to prevent.
    """

    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path
            if path not in opaque:
                yield from _field_paths(item, path, opaque)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            if isinstance(item, (dict, list)):
                yield path
                if path not in opaque:
                    yield from _field_paths(item, path, opaque)


def require_field_inventory(
    vector: Any,
    *,
    golden: str,
    validated: set[str],
    descriptive: set[str],
    opaque: set[str] = frozenset(),
) -> None:
    """Hold a golden to its own field set, and say which fields carry weight.

    Without this a field could be added to a vector and nothing anywhere would
    notice. Measured rather than assumed: deleting any one of 79 of the 379
    field positions across these goldens left the whole suite green, so a
    reader had no way to tell a load-bearing field from a caption. Two of them
    were `commissioning_nonce` and `owner_domain_id` — inputs to the
    commissioning HMAC.

    The split is the point. `validated` means some assertion below fails if the
    value changes; `descriptive` means the field is documentation and is
    declared as such on purpose. Anything in neither set is refused, so a new
    field cannot enter a contract vector without somebody deciding which it is.
    """

    overlap = validated & descriptive
    if overlap:
        raise ConformanceError(
            f"{golden}: field is declared both validated and descriptive: {sorted(overlap)}"
        )
    unknown_opaque = opaque - validated - descriptive
    if unknown_opaque:
        raise ConformanceError(
            f"{golden}: opaque field is not declared at all: {sorted(unknown_opaque)}"
        )
    actual = set(_field_paths(vector, opaque=frozenset(opaque)))
    undeclared = actual - validated - descriptive
    if undeclared:
        raise ConformanceError(
            f"{golden}: golden vector has undeclared fields: {sorted(undeclared)}"
        )
    absent = (validated | descriptive) - actual
    if absent:
        raise ConformanceError(
            f"{golden}: declared fields are absent from the vector: {sorted(absent)}"
        )


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _load_schemas() -> tuple[dict[str, dict[str, Any]], Registry]:
    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource]] = []
    for path in sorted(ROOT.rglob("*.schema.json")):
        schema = load_json(path)
        Draft202012Validator.check_schema(schema)
        schema_id = schema.get("$id")
        if not schema_id:
            raise ConformanceError(f"schema has no $id: {path}")
        if schema_id in schemas:
            raise ConformanceError(f"duplicate schema $id: {schema_id}")
        schemas[schema_id] = schema
        resources.append((schema_id, Resource.from_contents(schema)))
    return schemas, Registry().with_resources(resources)


def check_fixtures(schemas: dict[str, dict[str, Any]], registry: Registry) -> int:
    count = 0
    for kind in ("valid", "invalid"):
        for path in sorted((ROOT / "examples" / kind).glob("*.json")):
            fixture_file = load_json(path)
            for case in fixture_file["cases"]:
                count += 1
                schema_id = case["schema"]
                definition = case["definition"]
                if schema_id not in schemas:
                    raise ConformanceError(f"{case['case_id']}: unknown schema {schema_id}")
                if definition not in schemas[schema_id].get("$defs", {}):
                    raise ConformanceError(f"{case['case_id']}: unknown definition {definition}")
                validator = Draft202012Validator(
                    {"$ref": f"{schema_id}#/$defs/{definition}"},
                    registry=registry,
                    format_checker=FORMAT_CHECKER,
                )
                errors = sorted(
                    validator.iter_errors(case["value"]), key=lambda item: list(item.path)
                )
                if kind == "valid" and errors:
                    raise ConformanceError(
                        f"{case['case_id']}: expected valid, got {errors[0].message}"
                    )
                if kind == "invalid" and not errors:
                    raise ConformanceError(f"{case['case_id']}: invalid fixture was accepted")
                expected = case.get("error_contains")
                if errors and expected and not any(expected in error.message for error in errors):
                    messages = "; ".join(error.message for error in errors)
                    raise ConformanceError(
                        f"{case['case_id']}: expected error containing {expected!r}, got {messages}"
                    )
    return count


def check_canonical_vectors() -> int:
    document = load_json(ROOT / "golden" / "canonical-vectors.json")
    # The canonicalisation these vectors are vectors *of*. `canonical_bytes`
    # below is RFC 8785; left unread, this file could have named another
    # standard and still been checked with JCS — agreement on a canonical form
    # nobody used.
    if document["standard"] != "RFC 8785":
        raise ConformanceError("canonical vectors name a standard this check does not apply")
    vectors = document["vectors"]
    for vector in vectors:
        actual = canonical_bytes(vector["value"])
        expected = vector["canonical_utf8"].encode("utf-8")
        if actual != expected:
            raise ConformanceError(
                f"{vector['vector_id']}: canonical bytes mismatch: {actual!r} != {expected!r}"
            )
        expected_hash = vector.get("sha256")
        if expected_hash and hashlib.sha256(actual).hexdigest() != expected_hash:
            raise ConformanceError(f"{vector['vector_id']}: canonical SHA-256 mismatch")
    for index, vector in enumerate(vectors):
        require_field_inventory(
            vector,
            golden=f"canonical-vectors[{index}]",
            validated={"value", "canonical_utf8"} | ({"sha256"} if "sha256" in vector else set()),
            descriptive={"vector_id", "source"},
            # The document being canonicalised. Its shape is the test input.
            opaque={"value"},
        )
    require_field_inventory(
        document,
        golden="canonical-vectors",
        opaque={f"vectors[{index}].value" for index in range(len(vectors))},
        validated={"standard", "vectors"}
        | {f"vectors[{index}]" for index in range(len(vectors))}
        | {
            f"vectors[{index}].{field}"
            for index, vector in enumerate(vectors)
            for field in vector
        },
        descriptive=set(),
    )
    return len(vectors)


def _canonical_vector(vector_id: str) -> dict[str, Any]:
    vectors = load_json(ROOT / "golden" / "canonical-vectors.json")["vectors"]
    return next(vector for vector in vectors if vector["vector_id"] == vector_id)


def _apply_mutation(value: Any, mutation: dict[str, Any]) -> Any:
    result = copy.deepcopy(value)
    parts = [part for part in mutation["path"].split("/") if part]
    target = result
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = mutation["value"]
    return result


def check_es256_vectors() -> int:
    document = load_json(ROOT / "golden" / "es256-vectors.json")
    # The algorithm and encoding are asserted below by construction — 64 raw
    # bytes split into r and s, base64url without padding. Naming them and not
    # reading them let the file declare one thing while this check did another.
    declared = (
        document["profile_id"],
        document["signature_algorithm"],
        document["signature_encoding"],
    )
    if declared != (
        "eidolon-trust-p256-hpke-v1",
        "ES256",
        "64-byte-r-concat-s-base64url-no-padding",
    ):
        raise ConformanceError("ES256 vectors declare a profile or encoding this check does not use")
    vectors = document["vectors"]
    for vector in vectors:
        canonical = _canonical_vector(vector["canonical_vector_id"])
        value = canonical["value"]
        if "mutation" in vector:
            value = _apply_mutation(value, vector["mutation"])
        message = canonical_bytes(value)
        spki = _b64url_decode(vector["public_key_spki_base64url"])
        key_id = "sha256:" + hashlib.sha256(spki).hexdigest()
        if key_id != vector["key_id"]:
            raise ConformanceError(f"{vector['vector_id']}: SPKI key id mismatch")
        public_key = serialization.load_der_public_key(spki)
        if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
            public_key.curve, ec.SECP256R1
        ):
            raise ConformanceError(f"{vector['vector_id']}: key is not P-256")
        raw = _b64url_decode(vector["signature"])
        if len(raw) != 64:
            raise ConformanceError(f"{vector['vector_id']}: ES256 signature is not 64 bytes")
        signature = encode_dss_signature(
            int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
        )
        verified = True
        try:
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            verified = False
        if verified is not vector["valid"]:
            raise ConformanceError(f"{vector['vector_id']}: signature verdict mismatch")
    for index, vector in enumerate(vectors):
        require_field_inventory(
            vector,
            golden=f"es256-vectors[{index}]",
            validated={
                "canonical_vector_id",
                "key_id",
                "public_key_spki_base64url",
                "signature",
                "valid",
            }
            | ({"mutation", "mutation.path", "mutation.value"} if "mutation" in vector else set()),
            descriptive={"vector_id"},
        )
    require_field_inventory(
        document,
        golden="es256-vectors",
        validated={
            "profile_id", "signature_algorithm", "signature_encoding", "vectors",
        }
        | {f"vectors[{index}]" for index in range(len(vectors))}
        | {
            f"vectors[{index}].{field}"
            for index, vector in enumerate(vectors)
            for field in vector
        }
        | {
            f"vectors[{index}].mutation.{field}"
            for index, vector in enumerate(vectors)
            if "mutation" in vector
            for field in vector["mutation"]
        },
        descriptive=set(),
    )
    return len(vectors)


def check_device_local_erase_vector() -> int:
    vector = load_json(ROOT / "golden" / "device-local-erase.json")
    operation = canonical_bytes(vector["operation"])
    if operation != vector["operation_canonical_utf8"].encode("utf-8"):
        raise ConformanceError("device-local.erase canonical operation bytes drifted")
    if "sha256:" + hashlib.sha256(operation).hexdigest() != vector["operation_fingerprint"]:
        raise ConformanceError("device-local.erase request fingerprint drifted")
    spki = _b64url_decode(vector["public_key_spki"])
    if "sha256:" + hashlib.sha256(spki).hexdigest() != vector["key_id"]:
        raise ConformanceError("device-local.erase ACK key id drifted")
    key = serialization.load_der_public_key(spki)
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ConformanceError("device-local.erase ACK key is not P-256")
    for document_name, canonical_name, signature_name in (
        ("ack_signing_document", "ack_canonical_utf8", "ack_signature"),
        ("key_proof_signing_document", None, "key_proof_signature"),
    ):
        message = canonical_bytes(vector[document_name])
        if canonical_name and message != vector[canonical_name].encode("utf-8"):
            raise ConformanceError(f"{document_name} canonical bytes drifted")
        raw = _b64url_decode(vector[signature_name])
        if len(raw) != 64:
            raise ConformanceError(f"{signature_name} is not 64-byte R||S")
        signature = encode_dss_signature(
            int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
        )
        try:
            key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise ConformanceError(f"{signature_name} is invalid") from exc
    return 1


def check_device_manifest_vector() -> int:
    """The bytes a board must emit, checked against the shape that admits them.

    A producer vector, not a schema example: it exists so the device firmware can
    assert its own output rather than a copy of it. The copy is what drifts — the
    setup descriptor was a field table written by hand at both ends, kept in step
    by a person comparing two files, and every device out of the box ended up
    telling the controller its own description broke the contract.
    """

    document = load_json(ROOT / "golden" / "device-manifest.json")
    cases = document["cases"]
    if not cases:
        raise ConformanceError("device manifest vector carries no case")
    seen: set[tuple[str, bool]] = set()
    for case in cases:
        name = f"{case['board_name']}/camera={case['has_camera']}"
        parsed = json.loads(case["canonical_utf8"])
        # The vector's bytes must be the canonical form of the vector's own
        # document, or the firmware would be pinned to bytes nothing else agrees
        # describe this Manifest.
        if canonical_bytes(parsed).decode("utf-8") != case["canonical_utf8"]:
            raise ConformanceError(f"{name}: canonical_utf8 is not RFC 8785 of its document")
        if manifest_digest(parsed) != case["digest"]:
            raise ConformanceError(f"{name}: digest does not describe the document")
        # And the bytes a device emits must be a document the entry admits.
        # This is the whole point of the vector: the producer and the gate are
        # checked against one definition instead of agreeing by coincidence.
        DeviceCapabilityManifest.model_validate(parsed)
        if parsed["title"] != case["board_name"]:
            raise ConformanceError(f"{name}: title is not the board name it was built from")
        kinds = [item["kind"] for item in parsed["media"]]
        if ("video" in kinds) != bool(case["has_camera"]):
            raise ConformanceError(f"{name}: declared video does not match the build")
        modes = {
            item["schema"]["const"]
            for item in parsed["properties"]
            if item["name"] == "interaction_mode"
        }
        if modes != {case["interaction_mode"]}:
            raise ConformanceError(f"{name}: declared interaction_mode does not match the build")
        key = (case["interaction_mode"], bool(case["has_camera"]))
        if key in seen:
            raise ConformanceError(f"{name}: two vectors for one build profile")
        seen.add(key)
    return len(cases)


def check_device_delivery_vector() -> int:
    vector = load_json(ROOT / "golden" / "device-delivery.json")
    for name in ("deliver", "acceptance", "evidence"):
        canonical = canonical_bytes(vector[name])
        if canonical != vector[f"{name}_canonical_utf8"].encode("utf-8"):
            raise ConformanceError(f"device delivery {name} canonical bytes drifted")
        digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
        if digest != vector[f"{name}_sha256"]:
            raise ConformanceError(f"device delivery {name} digest drifted")
    # The acknowledgement this vector delivers is the one the erase vector
    # signs, so it is compared against that document and its signature is
    # verified — not merely counted. Asserting the field's presence let a
    # second, unverifiable signature over the same document live here unnoticed.
    erase = load_json(ROOT / "golden" / "device-local-erase.json")
    acknowledged = dict(vector["evidence"]["payload"])
    signature = acknowledged.pop("device_signature", None)
    if signature is None:
        raise ConformanceError("device delivery evidence dropped the device signature")
    if acknowledged != erase["ack_signing_document"]:
        raise ConformanceError(
            "device delivery evidence acknowledges a different document than the erase vector signs"
        )
    raw = _b64url_decode(signature)
    if len(raw) != 64:
        raise ConformanceError("device delivery evidence signature is not 64-byte R||S")
    key = serialization.load_der_public_key(_b64url_decode(erase["public_key_spki"]))
    try:
        key.verify(
            encode_dss_signature(
                int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
            ),
            canonical_bytes(acknowledged),
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature as exc:
        raise ConformanceError("device delivery evidence signature is invalid") from exc
    if "terminal_result" in vector["acceptance"]:
        raise ConformanceError("delivery acceptance claims an operation terminal result")
    return 1


def check_claim_revoke_vector() -> int:
    vector = load_json(ROOT / "golden" / "claim-revoke.json")
    canonical = canonical_bytes(vector["fingerprint_document"])
    if canonical != vector["canonical_fingerprint_utf8"].encode("utf-8"):
        raise ConformanceError("Claim revoke canonical fingerprint bytes drifted")
    fingerprint = "sha256:" + hashlib.sha256(canonical).hexdigest()
    if fingerprint != vector["fingerprint"]:
        raise ConformanceError("Claim revoke fingerprint drifted")
    if set(vector["excluded_from_fingerprint"]) != {"command_id", "correlation_id"}:
        raise ConformanceError("Claim revoke retry/audit metadata entered semantic equality")
    if any(field not in vector["command"] for field in vector["excluded_from_fingerprint"]):
        raise ConformanceError("Claim revoke golden command omits excluded retry/audit fields")
    if any(
        field in vector["fingerprint_document"]
        for field in vector["excluded_from_fingerprint"]
    ):
        raise ConformanceError("Claim revoke fingerprint document contains excluded fields")
    # What the fingerprint is actually taken over, derived from the command
    # rather than trusted beside it. The command and the document were two
    # independent objects here: the whole `device_ref` subtree could be deleted
    # from the command with this suite still green, so a vector could fingerprint
    # a document that was not the command it sits next to.
    command = vector["command"]
    excluded = set(vector["excluded_from_fingerprint"])
    expected_payload = {
        key: value
        for key, value in command.items()
        if key not in excluded and key != "operation"
    }
    if vector["fingerprint_document"]["payload"] != expected_payload:
        raise ConformanceError(
            "Claim revoke fingerprint payload is not the command minus its excluded fields"
        )
    if vector["fingerprint_document"]["owner_domain_id"] != command["device_ref"]["owner_domain_id"]:
        raise ConformanceError("Claim revoke fingerprint is scoped to another Owner Domain")
    # Two names for one operation, and nothing derives either from the other:
    # the wire command says `operation`, the fingerprint document says
    # `command_type`. Both are pinned so that changing one without the other is
    # red rather than a silent divergence between what is sent and what is
    # fingerprinted.
    if (command["operation"], vector["fingerprint_document"]["command_type"]) != (
        "device.claim-revocation",
        "device.claim.revoke",
    ):
        raise ConformanceError("Claim revoke operation naming drifted")
    require_field_inventory(
        vector,
        golden="claim-revoke",
        validated={
            "command",
            "command.command_id", "command.correlation_id", "command.operation",
            "command.reason", "command.device_ref",
            "command.device_ref.device_instance_id",
            "command.device_ref.owner_domain_id",
            "command.device_ref.owner_domain_generation",
            "command.device_ref.claim_generation",
            "command.device_ref.trust_epoch",
            "fingerprint_document",
            "fingerprint_document.command_type",
            "fingerprint_document.owner_domain_id",
            "fingerprint_document.payload",
            "fingerprint_document.payload.device_ref",
            "fingerprint_document.payload.device_ref.device_instance_id",
            "fingerprint_document.payload.device_ref.owner_domain_id",
            "fingerprint_document.payload.device_ref.owner_domain_generation",
            "fingerprint_document.payload.device_ref.claim_generation",
            "fingerprint_document.payload.device_ref.trust_epoch",
            "fingerprint_document.payload.reason",
            "canonical_fingerprint_utf8", "fingerprint", "excluded_from_fingerprint",
        },
        descriptive=set(),
    )
    return 1


def check_owner_directory_vector() -> int:
    vector = load_json(ROOT / "golden" / "owner-domain-descriptor.json")
    descriptor = vector["descriptor"]
    signing_document = {key: value for key, value in descriptor.items() if key != "signature"}
    message = canonical_bytes(signing_document)
    if message != vector["canonical_signing_utf8"].encode("utf-8"):
        raise ConformanceError("Owner directory canonical signing bytes drifted")
    key = serialization.load_pem_public_key(vector["authority_signing_spki_pem"].encode("ascii"))
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ConformanceError("Owner directory signer is not P-256")
    spki = key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if descriptor["signing_key_id"] != "sha256:" + hashlib.sha256(spki).hexdigest():
        raise ConformanceError("Owner directory signing key id drifted")
    raw = _b64url_decode(descriptor["signature"])
    if len(raw) != 64:
        raise ConformanceError("Owner directory signature is not 64-byte P1363")
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    try:
        key.verify(der, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise ConformanceError("Owner directory signature is invalid") from exc
    if vector["profile_id"] != "eidolon-trust-p256-hpke-v1":
        raise ConformanceError("Owner directory vector declares another trust profile")
    require_field_inventory(
        vector,
        golden="owner-domain-descriptor",
        validated={
            "profile_id", "authority_signing_spki_pem", "canonical_signing_utf8",
            "descriptor",
            "descriptor.descriptor_uri", "descriptor.directory_revision",
            "descriptor.endpoints", "descriptor.expires_at", "descriptor.issued_at",
            "descriptor.owner_domain_generation", "descriptor.owner_domain_id",
            "descriptor.signature", "descriptor.signing_key_id",
            "descriptor.trust_root_refs",
        },
        descriptive={"vector_id"},
        # Every endpoint is inside the signed canonical bytes above, so a field
        # added to one is already held by the signature rather than by a name.
        opaque={"descriptor.endpoints"},
    )
    return 1


def check_setup_descriptor_vector(
    schemas: dict[str, dict[str, Any]], registry: Registry
) -> int:
    """Hold the setup descriptor golden vector and its schema to each other.

    Both ends of the setup act read this vector: the firmware compares the bytes
    it serialises against it, and the controller parses it through the generated
    binding. That only protects them while the vector still says what the schema
    says. The descriptor is the one DTO in this act that used to be hand-written
    on both sides, and it drifted where nothing was watching: an unbounded window
    was encoded as `expires_in_seconds: 0`, which the controller read as a
    duration no device could honour and refused — every device out of the box.
    """

    vector = load_json(ROOT / "golden" / "setup-descriptor.json")
    definition = schemas[
        "https://contracts.eidolon.live/device-foundation/v1/common/schemas.schema.json"
    ]["$defs"]["SetupDescriptor"]
    if vector["required_fields"] != definition["required"]:
        raise ConformanceError("setup descriptor vector and schema disagree on required fields")
    declared = sorted(vector["required_fields"] + vector["optional_fields"])
    if declared != sorted(definition["properties"]):
        raise ConformanceError("setup descriptor vector does not cover every declared field")
    if vector["optional_fields"] != ["expires_in_seconds"]:
        raise ConformanceError("only the setup window duration may be absent from a descriptor")
    validator = Draft202012Validator(
        {"$ref": vector["schema"]}, registry=registry, format_checker=FORMAT_CHECKER
    )
    for shape in ("bounded_window", "no_deadline"):
        descriptor = vector[shape]["descriptor"]
        errors = list(validator.iter_errors(descriptor))
        if errors:
            raise ConformanceError(f"setup descriptor {shape} is invalid: {errors[0].message}")
        canonical = canonical_bytes(descriptor)
        if canonical.decode("utf-8") != vector[shape]["canonical_utf8"]:
            raise ConformanceError(f"setup descriptor {shape} canonical bytes mismatch")
        if "sha256:" + hashlib.sha256(canonical).hexdigest() != vector[shape]["canonical_sha256"]:
            raise ConformanceError(f"setup descriptor {shape} canonical digest mismatch")
    if "expires_in_seconds" in vector["no_deadline"]["descriptor"]:
        raise ConformanceError("an offer with no deadline must name no duration at all")
    # An absent duration is the only way to say "this offer does not end". Every
    # number a producer could reach for instead has to stay invalid, or the
    # sentinel comes back.
    for encoded in vector["rejected_expires_in_seconds"]:
        candidate = dict(vector["bounded_window"]["descriptor"])
        candidate["expires_in_seconds"] = encoded
        if validator.is_valid(candidate):
            raise ConformanceError(f"setup descriptor accepted {encoded!r} as a window duration")
    # The trust values a descriptor may carry, held to the schema rather than
    # listed beside it. Unread, this was a second statement of the enum: a value
    # could be added to the schema and never appear here, or listed here and
    # never be accepted.
    if vector["trust_values"] != definition["properties"]["trust"]["enum"]:
        raise ConformanceError("setup descriptor trust values and schema disagree")
    for shape in ("bounded_window", "no_deadline"):
        descriptor = vector[shape]["descriptor"]
        if descriptor["trust"] not in vector["trust_values"]:
            raise ConformanceError(f"setup descriptor {shape} carries an undeclared trust value")
        if descriptor["contract_version"] != vector["contract_version"]:
            raise ConformanceError(
                f"setup descriptor {shape} is not the contract version this vector declares"
            )
    require_field_inventory(
        vector,
        golden="setup-descriptor",
        validated={
            "contract_version", "schema", "required_fields", "optional_fields",
            "trust_values", "rejected_expires_in_seconds",
            "bounded_window", "bounded_window.descriptor",
            "bounded_window.canonical_utf8", "bounded_window.canonical_sha256",
            "no_deadline", "no_deadline.descriptor",
            "no_deadline.canonical_utf8", "no_deadline.canonical_sha256",
        },
        descriptive={"vector_id"},
        # Each descriptor is validated against the schema and pinned by its own
        # canonical digest above, so a field added to one is already held.
        opaque={"bounded_window.descriptor", "no_deadline.descriptor"},
    )
    return 1


def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt or bytes(32), ikm, hashlib.sha256).digest()


def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    output = b""
    block = b""
    for counter in range(1, math.ceil(length / 32) + 1):
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        output += block
    return output[:length]


def _labeled_extract(suite_id: bytes, salt: bytes, label: bytes, ikm: bytes) -> bytes:
    return _hkdf_extract(salt, b"HPKE-v1" + suite_id + label + ikm)


def _labeled_expand(suite_id: bytes, prk: bytes, label: bytes, info: bytes, length: int) -> bytes:
    labeled_info = length.to_bytes(2, "big") + b"HPKE-v1" + suite_id + label + info
    return _hkdf_expand(prk, labeled_info, length)


def _derive_p256_key(ikm: bytes) -> ec.EllipticCurvePrivateKey:
    suite_id = b"KEM" + (16).to_bytes(2, "big")
    dkp_prk = _labeled_extract(suite_id, b"", b"dkp_prk", ikm)
    for counter in range(256):
        candidate = _labeled_expand(suite_id, dkp_prk, b"candidate", bytes([counter]), 32)
        scalar = int.from_bytes(candidate, "big")
        if 0 < scalar < P256_ORDER:
            return ec.derive_private_key(scalar, ec.SECP256R1())
    raise ConformanceError("RFC 9180 P-256 DeriveKeyPair exhausted")


def _serialize_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def check_hpke_vector() -> int:
    vector = load_json(ROOT / "golden" / "rfc9180-p256-base.json")
    if (vector["mode"], vector["kem_id"], vector["kdf_id"], vector["aead_id"]) != (0, 16, 1, 1):
        raise ConformanceError("RFC 9180 vector does not use the frozen ciphersuite")
    sk_e = _derive_p256_key(bytes.fromhex(vector["ikmE"]))
    sk_r = _derive_p256_key(bytes.fromhex(vector["ikmR"]))
    pk_e = _serialize_public(sk_e.public_key())
    pk_r = _serialize_public(sk_r.public_key())
    if pk_e.hex() != vector["pkEm"] or pk_r.hex() != vector["pkRm"]:
        raise ConformanceError("RFC 9180 DeriveKeyPair mismatch")
    if sk_e.private_numbers().private_value.to_bytes(32, "big").hex() != vector["skEm"]:
        raise ConformanceError("RFC 9180 sender private key mismatch")
    if sk_r.private_numbers().private_value.to_bytes(32, "big").hex() != vector["skRm"]:
        raise ConformanceError("RFC 9180 recipient private key mismatch")

    kem_suite = b"KEM" + (16).to_bytes(2, "big")
    dh = sk_e.exchange(ec.ECDH(), sk_r.public_key())
    eae_prk = _labeled_extract(kem_suite, b"", b"eae_prk", dh)
    shared_secret = _labeled_expand(kem_suite, eae_prk, b"shared_secret", pk_e + pk_r, 32)
    if shared_secret.hex() != vector["shared_secret"] or pk_e.hex() != vector["enc"]:
        raise ConformanceError("RFC 9180 DHKEM mismatch")

    suite = b"HPKE" + (16).to_bytes(2, "big") + (1).to_bytes(2, "big") + (1).to_bytes(2, "big")
    info = bytes.fromhex(vector["info"])
    psk_id_hash = _labeled_extract(suite, b"", b"psk_id_hash", b"")
    info_hash = _labeled_extract(suite, b"", b"info_hash", info)
    context = b"\x00" + psk_id_hash + info_hash
    secret = _labeled_extract(suite, shared_secret, b"secret", b"")
    key = _labeled_expand(suite, secret, b"key", context, 16)
    nonce = _labeled_expand(suite, secret, b"base_nonce", context, 12)
    exporter = _labeled_expand(suite, secret, b"exp", context, 32)
    expected = {
        "key_schedule_context": context,
        "secret": secret,
        "key": key,
        "base_nonce": nonce,
        "exporter_secret": exporter,
    }
    for name, actual in expected.items():
        if actual.hex() != vector[name]:
            raise ConformanceError(f"RFC 9180 {name} mismatch")
    encryption = vector["encryption"]
    # The per-message nonce is derived, not read. RFC 9180 seals with
    # `base_nonce XOR seq`, and taking `nonce` as given left both it and
    # `sequence_number` unchecked — the vector could have named any sequence
    # number and still passed, so the one rule that ties a message to its
    # position in the stream was stated in the vector and enforced nowhere.
    sequence_number = encryption["sequence_number"]
    derived_nonce = (
        int.from_bytes(nonce, "big") ^ sequence_number
    ).to_bytes(len(nonce), "big")
    if derived_nonce.hex() != encryption["nonce"]:
        raise ConformanceError(
            "RFC 9180 message nonce is not base_nonce XOR the sequence number"
        )
    ciphertext = AESGCM(key).encrypt(
        derived_nonce,
        bytes.fromhex(encryption["plaintext"]),
        bytes.fromhex(encryption["aad"]),
    )
    if ciphertext.hex() != encryption["ciphertext"]:
        raise ConformanceError("RFC 9180 AES-128-GCM ciphertext mismatch")
    require_field_inventory(
        vector,
        golden="rfc9180-p256-base",
        validated={
            "mode", "kem_id", "kdf_id", "aead_id",
            "ikmE", "ikmR", "skEm", "skRm", "pkEm", "pkRm",
            "enc", "shared_secret", "info",
            "key_schedule_context", "secret", "key", "base_nonce",
            "exporter_secret",
            "encryption",
            "encryption.sequence_number",
            "encryption.nonce",
            "encryption.plaintext",
            "encryption.aad",
            "encryption.ciphertext",
        },
        descriptive={"vector_id", "source"},
    )
    return 1


def check_claim_grant_aad() -> int:
    vector = load_json(ROOT / "golden" / "claim-grant-aad.json")
    aad = canonical_bytes(vector["aad"])
    # The bytes, then their digest. A consumer that has to build this AAD needs
    # the string: the digest can only tell it that it disagrees, and every such
    # consumer would otherwise need a hash implementation in whatever suite
    # builds the bytes just to read this vector at all.
    if aad.decode() != vector["canonical_aad_utf8"]:
        raise ConformanceError("ClaimGrant AAD canonical bytes drifted")
    if hashlib.sha256(aad).hexdigest() != vector["canonical_aad_sha256"]:
        raise ConformanceError("ClaimGrant AAD canonical digest mismatch")
    # The AEAD is named by the vector and decrypted with AES-GCM below. Left
    # unread, a vector could name any other AEAD and still be decrypted with
    # this one — the suite would report agreement on a cipher nobody used.
    if vector["test_aead"] != "AES-128-GCM":
        raise ConformanceError("ClaimGrant AAD vector names an AEAD this check does not use")
    # Every AAD field must appear in the negative matrix, derived from the AAD
    # rather than restated: a field added to the AAD and forgotten here would
    # be a field whose mutation nobody proves is rejected.
    if set(vector["mutate_each_field_must_fail"]) != set(vector["aad"]):
        raise ConformanceError(
            "ClaimGrant AAD negative matrix does not cover exactly the AAD's own fields"
        )
    key = bytes.fromhex(vector["test_key"])
    nonce = bytes.fromhex(vector["test_nonce"])
    plaintext = bytes.fromhex(vector["plaintext"])
    ciphertext = bytes.fromhex(vector["ciphertext"])
    if AESGCM(key).decrypt(nonce, ciphertext, aad) != plaintext:
        raise ConformanceError("ClaimGrant AAD positive decrypt mismatch")
    for field in vector["mutate_each_field_must_fail"]:
        mutated = copy.deepcopy(vector["aad"])
        value = mutated[field]
        if isinstance(value, str):
            mutated[field] = value + "-mutated"
        elif isinstance(value, int):
            mutated[field] = value + 1
        else:
            mutated[field] = {**value, "revision": value["revision"] + 1}
        try:
            AESGCM(key).decrypt(nonce, ciphertext, canonical_bytes(mutated))
        except InvalidTag:
            continue
        raise ConformanceError(f"ClaimGrant AAD mutation did not fail: {field}")
    require_field_inventory(
        vector,
        golden="claim-grant-aad",
        validated={
            "aad",
            "aad.contract", "aad.profile_id", "aad.enrollment_id",
            "aad.proposal_revision", "aad.device_instance_id",
            "aad.hardware_evidence_digest", "aad.manifest_ref",
            "aad.manifest_ref.manifest_id", "aad.manifest_ref.revision",
            "aad.manifest_ref.digest", "aad.owner_domain_id",
            "aad.owner_domain_generation", "aad.claim_generation",
            "aad.trust_epoch", "aad.grant_id",
            "canonical_aad_utf8", "canonical_aad_sha256",
            "test_aead", "test_key", "test_nonce",
            "plaintext", "ciphertext", "mutate_each_field_must_fail",
        },
        descriptive={"vector_id"},
    )
    return 1 + len(vector["mutate_each_field_must_fail"])


def check_claim_grant_wire_envelope() -> int:
    vector = load_json(ROOT / "golden" / "claim-grant-wire-envelope.json")
    encoded = canonical_bytes(vector["envelope"]["aad"])
    if encoded.decode() != vector["aad_canonical_utf8"]:
        raise ConformanceError("ClaimGrant wire-envelope AAD canonical bytes drifted")
    if "sha256:" + hashlib.sha256(encoded).hexdigest() != vector["aad_sha256"]:
        raise ConformanceError("ClaimGrant wire-envelope AAD digest drifted")
    envelope = vector["envelope"]
    # The suite the envelope declares, held to the frozen profile. These five
    # were readable and unread: every one of them could be deleted with this
    # suite still green, so an envelope could have announced another KEM, KDF
    # or AEAD and nothing here would have disagreed.
    declared_suite = (
        envelope["contract"],
        envelope["profile_id"],
        envelope["kem"],
        envelope["kdf"],
        envelope["aead"],
    )
    if declared_suite != (
        "eidolon.device-foundation.claim-grant-envelope",
        "eidolon-trust-p256-hpke-v1",
        "DHKEM-P256-HKDF-SHA256",
        "HKDF-SHA256",
        "AES-128-GCM",
    ):
        raise ConformanceError("ClaimGrant wire envelope does not declare the frozen suite")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", envelope["recipient_handoff_key_id"]):
        raise ConformanceError("ClaimGrant recipient handoff key id is not a sha256 digest")
    for name in ("encapsulated_key", "ciphertext"):
        if not _b64url_decode(envelope[name]):
            raise ConformanceError(f"ClaimGrant wire envelope {name} is empty")
    # Derived from the envelope rather than restated beside it. The set used to
    # be written out here by hand, which made it a second statement of the
    # envelope's shape: a field added to the envelope would not have been
    # required to appear in the pre-open negative matrix.
    expected = set(envelope) - {"contract"}
    if set(vector["pre_open_mutations_must_fail"]) != expected:
        raise ConformanceError("ClaimGrant pre-open negative matrix is incomplete")
    require_field_inventory(
        vector,
        golden="claim-grant-wire-envelope",
        validated={
            "envelope",
            "envelope.contract", "envelope.profile_id", "envelope.kem",
            "envelope.kdf", "envelope.aead",
            "envelope.recipient_handoff_key_id", "envelope.encapsulated_key",
            "envelope.ciphertext", "envelope.aad",
            "envelope.aad.contract", "envelope.aad.profile_id",
            "envelope.aad.enrollment_id", "envelope.aad.proposal_revision",
            "envelope.aad.device_instance_id",
            "envelope.aad.hardware_evidence_digest",
            "envelope.aad.manifest_ref",
            "envelope.aad.manifest_ref.manifest_id",
            "envelope.aad.manifest_ref.revision",
            "envelope.aad.manifest_ref.digest",
            "envelope.aad.owner_domain_id",
            "envelope.aad.owner_domain_generation",
            "envelope.aad.claim_generation", "envelope.aad.trust_epoch",
            "envelope.aad.grant_id",
            "aad_canonical_utf8", "aad_sha256", "pre_open_mutations_must_fail",
        },
        descriptive={"vector_id"},
    )
    return 1 + len(expected)


def _leaf_paths(value: Any, prefix: str = "") -> list[str]:
    """Every position in a document that carries a value, dotted."""

    if isinstance(value, dict):
        found: list[str] = []
        for key, item in value.items():
            found.extend(_leaf_paths(item, f"{prefix}.{key}" if prefix else str(key)))
        return sorted(found)
    return [prefix]


def _mutate_leaf(document: Any, path: str) -> Any:
    mutated = copy.deepcopy(document)
    target = mutated
    *parents, last = path.split(".")
    for step in parents:
        target = target[step]
    value = target[last]
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ConformanceError(f"{path}: nothing sensible to mutate at a non-scalar leaf")
    target[last] = value + 1 if isinstance(value, int) else value + "-mutated"
    return mutated


def _verify_raw_p256(public_key_spki: str, document: Any, signature: str) -> bool:
    raw = _b64url_decode(signature)
    if len(raw) != 64:
        raise ConformanceError("proof signature is not 64-byte R||S")
    key = serialization.load_der_public_key(_b64url_decode(public_key_spki))
    try:
        key.verify(
            encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
            canonical_bytes(document),
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature:
        return False
    return True


def check_claim_grant_proof_vectors() -> int:
    """The two documents a device signs to take possession of a Claim.

    Neither is ever sent. The Authority rebuilds each one from the Proposal it
    holds and verifies a signature over its RFC 8785 bytes, so two ends that
    spell the document differently do not get an error naming the difference —
    they get an unverifiable proof, at the one step of enrolment a device
    cannot retry its way out of. Until these vectors the rule lived in a Python
    dict inside the Authority and in a hand-concatenated string inside the
    firmware, with nothing comparing them; the entry schema typed both proofs
    as `{"type": "string", "minLength": 16}`, which is true of any 16 bytes.

    Checked here rather than schema'd, deliberately: a JSON Schema cannot pin
    member order, and member order is exactly what a canonicalisation
    disagreement changes.
    """

    collection = load_json(ROOT / "golden" / "claim-grant-collection-proof.json")
    checks = _check_signed_document_vector(
        "claim-grant-collection-proof.json",
        claim_grant_collection_proof_document(
            enrollment_id=collection["document"]["enrollment_id"],
            proposal_revision=collection["document"]["proposal_revision"],
            collection_challenge=collection["document"]["collection_challenge"],
        ),
    )
    acknowledgement = load_json(ROOT / "golden" / "claim-grant-ack-proof.json")
    checks += _check_signed_document_vector(
        "claim-grant-ack-proof.json",
        claim_grant_ack_proof_document(
            enrollment_id=acknowledgement["document"]["enrollment_id"],
            grant_id=acknowledgement["document"]["grant_id"],
            device_ref=DeviceRef.model_validate(acknowledgement["document"]["device_ref"]),
        ),
    )

    # The acknowledgement is the named device speaking about itself. A proof by
    # any other key would be some device activating a Claim it is not the
    # subject of, and the two halves of that statement live in one document.
    named = acknowledgement["document"]["device_ref"]["device_instance_id"]
    derived = derive_device_instance_id(acknowledgement["public_key_spki"])
    if named != derived:
        raise ConformanceError(
            "the acknowledgement is signed by a key that is not the device_ref it names: "
            f"{named} vs {derived}"
        )
    checks += 1

    require_field_inventory(
        collection,
        golden="claim-grant-collection-proof",
        validated={
            "document", "document.contract", "document.enrollment_id",
            "document.proposal_revision", "document.collection_challenge",
            "canonical_utf8", "canonical_sha256", "public_key_spki", "key_id",
            "signature", "signature_algorithm", "signature_encoding",
            "mutate_each_field_must_fail",
        },
        descriptive={"vector_id", "description", "signing_key"},
    )
    require_field_inventory(
        acknowledgement,
        golden="claim-grant-ack-proof",
        validated={
            "document", "document.contract", "document.enrollment_id",
            "document.grant_id", "document.device_ref",
            "document.device_ref.device_instance_id",
            "document.device_ref.owner_domain_id",
            "document.device_ref.owner_domain_generation",
            "document.device_ref.claim_generation",
            "document.device_ref.trust_epoch",
            "canonical_utf8", "canonical_sha256", "public_key_spki", "key_id",
            "signature", "signature_algorithm", "signature_encoding",
            "mutate_each_field_must_fail",
        },
        descriptive={"vector_id", "description", "signing_key"},
    )
    return checks


def _check_signed_document_vector(name: str, rebuilt: Any) -> int:
    """One signing-document vector, against the bytes and the builder both.

    Shared by the ClaimGrant proofs and the Device Control proofs because they
    are one shape: a document neither side sends, rebuilt independently at each
    end, compared only through a signature. `rebuilt` is what the canonical
    Python definition produces from the vector's own inputs — without that
    comparison the vector would be a second authority that happens to agree
    today, which is the arrangement it exists to end.
    """

    vector = load_json(ROOT / "golden" / name)
    document = vector["document"]
    canonical = canonical_bytes(document)
    if canonical.decode("utf-8") != vector["canonical_utf8"]:
        raise ConformanceError(f"{name}: canonical_utf8 is not RFC 8785 of its own document")
    if "sha256:" + hashlib.sha256(canonical).hexdigest() != vector["canonical_sha256"]:
        raise ConformanceError(f"{name}: canonical digest does not describe the document")
    if canonical_bytes(rebuilt) != canonical:
        raise ConformanceError(f"{name}: the canonical builder no longer emits these bytes")
    if vector["signature_algorithm"] != "ES256":
        raise ConformanceError(f"{name}: names a signature algorithm this check does not use")
    if vector["signature_encoding"] != "64-byte-r-concat-s-base64url-no-padding":
        raise ConformanceError(f"{name}: names a signature encoding this check does not use")
    if (
        "sha256:" + hashlib.sha256(_b64url_decode(vector["public_key_spki"])).hexdigest()
        != vector["key_id"]
    ):
        raise ConformanceError(f"{name}: key_id does not describe the published key")
    if not _verify_raw_p256(vector["public_key_spki"], document, vector["signature"]):
        raise ConformanceError(f"{name}: the published signature does not verify")
    checks = 1
    if sorted(vector["mutate_each_field_must_fail"]) != _leaf_paths(document):
        raise ConformanceError(f"{name}: the negative matrix is not the document's own members")
    for member in vector["mutate_each_field_must_fail"]:
        if _verify_raw_p256(
            vector["public_key_spki"], _mutate_leaf(document, member), vector["signature"]
        ):
            raise ConformanceError(f"{name}: mutating {member} did not invalidate the proof")
        checks += 1
    return checks


def check_device_control_proof_vectors() -> int:
    """The two documents a device signs on the Device Control edge.

    The ClaimGrant proofs one step later, and with a worse symptom. These are
    the request behind `configuration:pull`, which is how a Body is handed its
    channel: a device that spells the document differently holds a Claim the
    Authority reports as active and is never given a room — and "active with no
    channel" is a state the product already cannot tell apart from waiting.

    Both were unpinned while all three implementations already existed: a dict
    in the Authority, a hand-concatenated string in the firmware, and an inline
    map in the phone.
    """

    configuration = load_json(ROOT / "golden" / "device-control-configuration-proof.json")
    checks = _check_signed_document_vector(
        "device-control-configuration-proof.json",
        device_control_configuration_proof_document(
            device_ref=DeviceRef.model_validate(configuration["document"]["device_ref"]),
            nonce=configuration["document"]["nonce"],
        ),
    )
    if configuration["document"]["operation_type"] != DEVICE_CONTROL_CONFIGURATION_OPERATION:
        raise ConformanceError("the configuration proof names an operation this contract does not")

    assertion = load_json(ROOT / "golden" / "device-control-manifest-assertion-proof.json")
    asserted = assertion["document"]
    # The digest the assertion signs must be a Manifest this contract already
    # publishes the bytes of. Otherwise the vector asserts a document nobody
    # can produce, and the two goldens could drift apart while both stay green.
    manifest_cases = load_json(ROOT / "golden" / "device-manifest.json")["cases"]
    asserted_case = next(
        (case for case in manifest_cases if case["digest"] == asserted["manifest_digest"]),
        None,
    )
    if asserted_case is None:
        raise ConformanceError(
            "the manifest assertion signs a digest no Manifest vector publishes"
        )
    checks += _check_signed_document_vector(
        "device-control-manifest-assertion-proof.json",
        AssertDeviceManifest(
            device_ref=DeviceRef.model_validate(asserted["device_ref"]),
            manifest=ManifestDocument(
                manifest_id="manifest_01",
                revision=1,
                digest=asserted["manifest_digest"],
                document=json.loads(asserted_case["canonical_utf8"]),
            ),
            nonce=asserted["nonce"],
            public_key_spki=assertion["public_key_spki"],
            device_signature=assertion["signature"],
        ).signing_document(),
    )
    if asserted["operation_type"] != MANIFEST_ASSERTION_OPERATION:
        raise ConformanceError("the manifest assertion names an operation this contract does not")

    # Both are the named device speaking about itself, as the acknowledgement is.
    for name, vector in (
        ("device-control-configuration-proof.json", configuration),
        ("device-control-manifest-assertion-proof.json", assertion),
    ):
        named = vector["document"]["device_ref"]["device_instance_id"]
        derived = derive_device_instance_id(vector["public_key_spki"])
        if named != derived:
            raise ConformanceError(
                f"{name}: signed by a key that is not the device_ref it names: {named} vs {derived}"
            )
        checks += 1
        require_field_inventory(
            vector,
            golden=name.removesuffix(".json"),
            validated={
                "document", "document.device_ref",
                "document.device_ref.device_instance_id",
                "document.device_ref.owner_domain_id",
                "document.device_ref.owner_domain_generation",
                "document.device_ref.claim_generation",
                "document.device_ref.trust_epoch",
                "document.nonce", "document.operation_type",
                *(("document.manifest_digest",) if "manifest_digest" in vector["document"] else ()),
                "canonical_utf8", "canonical_sha256", "public_key_spki", "key_id",
                "signature", "signature_algorithm", "signature_encoding",
                "mutate_each_field_must_fail",
            },
            descriptive={"vector_id", "description", "signing_key"},
        )
    return checks


def check_device_configuration_response(
    schemas: dict[str, dict[str, Any]], registry: Registry
) -> int:
    """The answer a Body gets, and what it must conclude from each one.

    The outer object had four readers or writers and no contract. Its danger is
    not a parse failure — a missing member fails loudly enough — it is that
    `lifecycle_state` and the presence of a channel are separate facts and
    nothing said so. "Approved, no channel yet" is the Authority holding the
    Claim while the Channel has not answered; a Body that reads it as failure
    abandons an enrolment that is fine, and one that reads it as active joins a
    room that does not exist. `纯软件Body准入方案.md` §4.3 records the product
    already collapsing that distinction, so the vector states the conclusion
    rather than leaving each parser to reach its own.
    """

    vector = load_json(ROOT / "golden" / "device-control-configuration-response.json")
    schema_id = (
        "https://contracts.eidolon.live/device-foundation/v1/device-control/schemas.schema.json"
    )
    validator = Draft202012Validator(
        {"$ref": f"{schema_id}#/$defs/DeviceConfigurationResult"},
        registry=registry,
        format_checker=FORMAT_CHECKER,
    )

    declared = list(vector["body_states"])
    seen: list[str] = []
    for case in vector["cases"]:
        case_id = case["case_id"]
        response = case["response"]
        canonical = canonical_bytes(response)
        if canonical.decode("utf-8") != case["canonical_utf8"]:
            raise ConformanceError(f"{case_id}: canonical_utf8 is not RFC 8785 of its response")
        if "sha256:" + hashlib.sha256(canonical).hexdigest() != case["canonical_sha256"]:
            raise ConformanceError(f"{case_id}: digest does not describe the response")
        errors = sorted(validator.iter_errors(response), key=lambda item: list(item.path))
        if errors:
            raise ConformanceError(f"{case_id}: the vector's own response is not admissible: "
                                   f"{errors[0].message}")
        if case["body_state"] not in declared:
            raise ConformanceError(f"{case_id}: states a conclusion this vector does not declare")
        if not case["why"]:
            raise ConformanceError(f"{case_id}: a case with no reason teaches nothing")
        seen.append(case["body_state"])
        if response["nonce"] != vector["request_nonce"]:
            raise ConformanceError(f"{case_id}: does not echo the nonce it answers")
        if response["device_ref"] != vector["device_ref"]:
            raise ConformanceError(f"{case_id}: answers about a different device")

    # Every declared conclusion has a case, exactly once. The awaiting-channel
    # case is the one worth having, so a vector that quietly lost it — or that
    # grew a second spelling of one state — must not pass.
    if sorted(seen) != sorted(declared) or len(seen) != len(set(seen)):
        raise ConformanceError(
            f"the response vector covers {sorted(seen)}, not its own declared {sorted(declared)}"
        )

    # The outer object and the document inside it, held together: the active
    # case carries the binding the session vector publishes, not a lookalike.
    inner = load_json(ROOT / "golden" / "livekit-session-binding.json")
    active = next(case for case in vector["cases"] if case["body_state"] == "active")
    channel = active["response"]["channels"][0]
    if channel["binding_format"] != inner["binding_format"]:
        raise ConformanceError("the active case names a binding format the session vector does not")
    if channel["opaque_binding"] != inner["opaque_binding"]:
        raise ConformanceError("the active case carries a binding the session vector does not")

    # What expiry may and may not be judged against, pinned rather than left to
    # each parser. A Body must not refuse a channel because its own clock says
    # the grant is spent: a device that has not reached NTP yet is the normal
    # state at boot, and refusing a fine channel there is worse than the failure
    # the check would prevent. So the accepted cases are deliberately already
    # past, and a consumer that wall-clocks them fails this vector rather than
    # passing it. The published rule and that property are checked together —
    # the sentence alone would be a caption.
    if vector["expiry_is_not_judged_against"] != "the reader's clock":
        raise ConformanceError("the response vector names an expiry rule this check does not hold")
    now_ms = int(time.time() * 1000)
    for case in vector["cases"]:
        for channel in case["response"]["channels"]:
            if channel["expires_at_ms"] <= channel["issued_at_ms"]:
                raise ConformanceError(
                    f"{case['case_id']}: an accepted grant is not internally coherent"
                )
            if channel["expires_at_ms"] >= now_ms:
                raise ConformanceError(
                    f"{case['case_id']}: this grant has not expired by the wall clock yet, so a "
                    "consumer that wrongly judges expiry against its own clock would still pass"
                )

    refusals = vector["must_refuse"]
    if not refusals:
        raise ConformanceError("the response vector carries no refusal case")
    for case in refusals:
        case_id = case["case_id"]
        if not case["why"]:
            raise ConformanceError(f"{case_id}: a refusal without a reason teaches nothing")
        if not sorted(validator.iter_errors(case["response"]), key=lambda item: list(item.path)):
            raise ConformanceError(f"{case_id}: the refused response is admissible")

    require_field_inventory(
        vector,
        golden="device-control-configuration-response",
        validated={
            "expiry_is_not_judged_against", "request_nonce", "device_ref",
            "device_ref.device_instance_id", "device_ref.owner_domain_id",
            "device_ref.owner_domain_generation", "device_ref.claim_generation",
            "device_ref.trust_epoch", "body_states", "cases",
            *(f"cases[{index}]" for index in range(len(vector["cases"]))),
            *(f"cases[{index}].{member}"
              for index in range(len(vector["cases"]))
              for member in ("case_id", "body_state", "response",
                             "canonical_utf8", "canonical_sha256")),
            "must_refuse",
            *(f"must_refuse[{index}]" for index in range(len(refusals))),
            *(f"must_refuse[{index}].{member}"
              for index in range(len(refusals))
              for member in ("case_id", "response")),
        },
        descriptive={
            "vector_id", "description", "schema",
            *(f"cases[{index}].why" for index in range(len(vector["cases"]))),
            *(f"must_refuse[{index}].why" for index in range(len(refusals))),
        },
        opaque={
            *(f"cases[{index}].response" for index in range(len(vector["cases"]))),
            *(f"must_refuse[{index}].response" for index in range(len(refusals))),
        },
    )
    return len(vector["cases"]) + len(refusals)


def check_livekit_session_binding() -> int:
    """The inside of `ChannelBinding.opaque_binding`, which two ends parse alone.

    The Authority relays this blob and its format string without reading
    either, and that opacity is correct — what a room is belongs to the
    Channel. It is not opaque to the pair that uses it. The Channel Provider
    writes the document and every Body parses it, and each of them held its own
    hand-written copy of the shape; `schema_version: 2` is the record of that
    having already gone wrong once, with nothing that would have said so.

    It has no canonical schema on purpose. `check_host_independence` refuses
    `room_name` as a key and `livekit` as a substring in every schema and valid
    example, because a Body's addressing must not be expressible in the
    vocabulary every Body shares. So the agreement lives in a vector, where
    naming a transport is what the artifact is for.
    """

    vector = load_json(ROOT / "golden" / "livekit-session-binding.json")
    binding = vector["binding"]
    canonical = canonical_bytes(binding)
    if canonical.decode("utf-8") != vector["canonical_utf8"]:
        raise ConformanceError("the LiveKit binding's canonical bytes are not RFC 8785 of it")
    if "sha256:" + hashlib.sha256(canonical).hexdigest() != vector["canonical_sha256"]:
        raise ConformanceError("the LiveKit binding's digest does not describe it")
    if sorted(vector["member_paths"]) != _leaf_paths(binding):
        raise ConformanceError("the LiveKit binding's member set is not the document's own")
    # Pinned whole, here, on purpose. `endswith` below ties the version to the
    # document, but a vector free to rename the media type could move the
    # agreement without anything deliberate happening; this document has moved
    # once already. Bumping it is meant to cost an edit in this file, which is
    # then a change every consumer's suite reports.
    if vector["binding_format"] != "application/vnd.eidolon.livekit-session+json;v=2":
        raise ConformanceError(
            "the LiveKit binding format string moved without this check moving with it"
        )
    if not vector["binding_format"].endswith(f";v={binding['schema_version']}"):
        raise ConformanceError("the binding format names a version the document does not carry")
    # The encoding, and the encoding it is not. Everything else base64 in this
    # contract — keys, signatures, proofs — is URL-safe and unpadded, so a
    # producer reaching for the house idiom here emits something no Body can
    # decode, and this is the pair of strings that says so.
    if vector["opaque_binding_encoding"] != "base64-standard-with-padding":
        raise ConformanceError("the vector names an encoding this check does not perform")
    if base64.b64encode(canonical).decode("ascii") != vector["opaque_binding"]:
        raise ConformanceError("the opaque binding is not standard base64 of the canonical bytes")
    if not vector["opaque_binding"].endswith("="):
        raise ConformanceError(
            "the opaque binding carries no padding, so it cannot separate the padded encoding "
            "from the unpadded one this contract uses everywhere else"
        )
    unpadded = vector["not_the_opaque_binding"]["base64url_no_padding"]
    if base64.urlsafe_b64encode(canonical).rstrip(b"=").decode("ascii") != unpadded:
        raise ConformanceError("the named wrong encoding is not the encoding it is named as")
    if unpadded == vector["opaque_binding"]:
        raise ConformanceError("the two encodings coincide, so this vector separates nothing")
    if base64.b64decode(vector["opaque_binding"], validate=True) != canonical:
        raise ConformanceError("the opaque binding does not decode to the canonical bytes")

    # Two lists, because the obligations differ. `must_refuse` is a document a
    # Body cannot act on at all. `may_refuse` is audio a Body that owns its
    # capture can decline and a Body whose transport negotiates the format must
    # not — requiring refusal there would make a working Body non-conformant.
    # What replaces the missing obligation is stated rather than left out.
    refusals = vector["must_refuse"] + vector["may_refuse"]
    if not vector["must_refuse"] or not vector["may_refuse"]:
        raise ConformanceError("the LiveKit binding vector lost one of its two refusal lists")
    if not vector["must_not_claim_unapplied_audio"].strip():
        raise ConformanceError(
            "the vector permits ignoring `audio` and no longer says what a Body owes instead"
        )
    seen: set[str] = set()
    for case in refusals:
        case_id = case["case_id"]
        if case_id in seen:
            raise ConformanceError(f"duplicate LiveKit binding refusal case {case_id}")
        seen.add(case_id)
        if not case["why"]:
            raise ConformanceError(f"{case_id}: a refusal without a reason teaches nothing")
        # A refusal case that is already the accepted document refuses nothing,
        # and a case whose members differ from the accepted one is testing the
        # member set rather than the value it claims to be about.
        if case["binding"] == binding:
            raise ConformanceError(f"{case_id}: the refused document is the accepted one")
        if case_id.endswith("NO-TOKEN"):
            continue
        if _leaf_paths(case["binding"]) != _leaf_paths(binding):
            raise ConformanceError(f"{case_id}: refuses a different shape, not a different value")

    require_field_inventory(
        vector,
        golden="livekit-session-binding",
        validated={
            "binding", "binding.schema_version", "binding.session",
            "binding.session.server_url", "binding.session.token",
            "binding.session.identity", "binding.session.room_name",
            "binding.audio", "binding.audio.sample_rate", "binding.audio.channels",
            "binding_format", "canonical_utf8", "canonical_sha256", "member_paths",
            "opaque_binding", "opaque_binding_encoding",
            "not_the_opaque_binding", "not_the_opaque_binding.base64url_no_padding",
            "must_refuse", "may_refuse", "must_not_claim_unapplied_audio",
            *(f"{key}[{index}]" for key in ("must_refuse", "may_refuse")
              for index in range(len(vector[key]))),
            *(f"{key}[{index}].binding" for key in ("must_refuse", "may_refuse")
              for index in range(len(vector[key]))),
            *(f"{key}[{index}].case_id" for key in ("must_refuse", "may_refuse")
              for index in range(len(vector[key]))),
        },
        descriptive={
            "vector_id", "description", "no_schema_because",
            *(f"{key}[{index}].why" for key in ("must_refuse", "may_refuse")
              for index in range(len(vector[key]))),
        },
        opaque={
            f"{key}[{index}].binding" for key in ("must_refuse", "may_refuse")
            for index in range(len(vector[key]))
        },
    )
    return 1 + len(refusals)


def check_admission_event_stream() -> int:
    vector = load_json(ROOT / "golden" / "admission-event-stream.json")
    digest = "sha256:" + hashlib.sha256(canonical_bytes(vector["event"])).hexdigest()
    if digest != vector["business_event_sha256"]:
        raise ConformanceError("Claim event business equality digest drifted")
    positions = [item["stream_position"] for item in vector["stream_items"]]
    if positions != [41, 42]:
        raise ConformanceError("Claim stream transport positions drifted")
    if set(vector["transport_fields_excluded_from_event_equality"]) != {
        "stream_position", "requested_after", "next_cursor", "high_watermark"
    }:
        raise ConformanceError("transport recovery fields entered event business equality")
    if set(vector["semantics"]) != {"duplicate", "gap", "restart", "replay"}:
        raise ConformanceError("Claim stream recovery semantics are incomplete")
    # The stream items are supposed to be the *same* business event delivered
    # twice. Nothing said so: `event_ref` was never read, so the vector could
    # have carried positions for an event it does not contain, which is exactly
    # the claim it exists to make.
    if {item["event_ref"] for item in vector["stream_items"]} != {vector["event"]["id"]}:
        raise ConformanceError("Claim stream items do not all reference this vector's event")
    require_field_inventory(
        vector,
        golden="admission-event-stream",
        validated={
            "event", "business_event_sha256", "semantics", "stream_items",
            "transport_fields_excluded_from_event_equality",
        }
        # Asserted as an exact set just above, so each key carries weight.
        | {f"semantics.{name}" for name in vector["semantics"]}
        | {f"stream_items[{index}]" for index in range(len(vector["stream_items"]))}
        | {
            f"stream_items[{index}].{field}"
            for index in range(len(vector["stream_items"]))
            for field in ("event_ref", "stream_position")
        },
        descriptive={"vector_id"},
        # Every field of the event is inside `business_event_sha256`, so one
        # added there is already held by the digest rather than by a name.
        opaque={"event"},
    )
    return 1


def check_protocomm_framing() -> int:
    vector = load_json(ROOT / "golden" / "protocomm-security2-framing.json")
    semantic = vector["semantic_empty_request"]
    actual = canonical_bytes(semantic["json"])
    if actual.hex() != semantic["canonical_utf8_hex"] or not actual:
        raise ConformanceError("Protocomm semantic-empty request framing mismatch")
    if semantic["zero_length_ciphertext_payload_allowed"]:
        raise ConformanceError("frozen profile must reject zero-length semantic requests")
    required_resources = {
        "salt",
        "verifier",
        "security-context",
        "endpoint-user-data",
        "callback-target",
    }
    if set(vector["session_owned_resources"]) != required_resources:
        raise ConformanceError("Protocomm session resource ownership is incomplete")
    # The profile these framing rules belong to. All three were readable and
    # unread, so this vector could have described another transport's framing
    # and still passed as this one's.
    if (vector["profile_id"], vector["protocol"], vector["security"]) != (
        "eidolon-trust-p256-hpke-v1",
        "ESP-IDF-Protocomm-Security2",
        "SRP6a-AES-256-GCM",
    ):
        raise ConformanceError("Protocomm vector describes another profile or transport")
    if vector["minimum_lifetime"] != "StartingTransport-through-Stopped":
        raise ConformanceError("Protocomm session lifetime boundary drifted")
    # The negative cases — the part of a framing contract that says what must be
    # refused. They were the least validated fields in any golden here: the
    # whole list could be deleted and nothing noticed, so a profile could stop
    # rejecting a zero-length semantic request without a single test changing.
    if {(case["case"], case["stable_error"]) for case in vector["invalid_cases"]} != {
        ("zero-length-semantic-request", "INVALID_ARGUMENT"),
        ("unknown-profile", "CONTRACT_UNSUPPORTED"),
    }:
        raise ConformanceError("Protocomm negative framing cases or their stable errors drifted")
    require_field_inventory(
        vector,
        golden="protocomm-security2-framing",
        validated={
            "profile_id", "protocol", "security", "minimum_lifetime",
            "session_owned_resources", "semantic_empty_request",
            "semantic_empty_request.json",
            "semantic_empty_request.canonical_utf8_hex",
            "semantic_empty_request.zero_length_ciphertext_payload_allowed",
            "invalid_cases",
        }
        | {f"invalid_cases[{index}]" for index in range(len(vector["invalid_cases"]))}
        | {
            f"invalid_cases[{index}].{field}"
            for index in range(len(vector["invalid_cases"]))
            for field in ("case", "stable_error")
        },
        descriptive={"vector_id"},
        # The request document whose canonical bytes are asserted above.
        opaque={"semantic_empty_request.json"},
    )
    return 1


def check_profile() -> int:
    profile = load_json(ROOT / "profile" / "eidolon-trust-p256-hpke-v1.json")
    if profile["profile_id"] != "eidolon-trust-p256-hpke-v1":
        raise ConformanceError("wrong trust profile id")
    if profile["algorithm_negotiation"] != "forbidden":
        raise ConformanceError("profile permits algorithm negotiation")
    if profile["signature"]["signature_bytes"] != 64:
        raise ConformanceError("profile does not freeze P1363 ES256 signatures")
    if profile["owner_domain_root"] != {
        "algorithm": "P-256",
        "certificate_profile": "self-signed-ca",
        "host_runtime_key": False,
        "installed_atomically_with_initial_directory": True,
        "recovery_requirement": "second-controller-or-encrypted-recovery-package",
    }:
        raise ConformanceError("Owner root profile drifted or became Host-bound")
    delegation = profile["authority_delegation"]
    if (
        delegation["issuer"] != "owner-domain-root"
        or delegation["certificate_basic_constraints_ca"] is not False
        or delegation["certificate_extended_key_usage"] != "code-signing"
        or delegation["private_key_in_host_runtime"] is not False
        or delegation["directory_signature_input"] != "RFC8785(descriptor-without-signature)"
    ):
        raise ConformanceError("Owner directory delegation profile drifted")
    if profile["claim_grant_handoff"] != {
        "standard": "RFC 9180",
        "mode": "base",
        "kem": "DHKEM-P256-HKDF-SHA256",
        "kdf": "HKDF-SHA256",
        "aead": "AES-128-GCM",
        "recipient_key": "proposal-one-time-handoff-key",
        "aad_schema": "https://contracts.eidolon.live/device-foundation/v1/common/schemas.schema.json#/$defs/ClaimGrantAAD",
    }:
        raise ConformanceError("profile HPKE suite drifted")
    return 1


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(key)
            keys.extend(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(_walk_keys(child))
    return keys


def check_host_independence() -> int:
    forbidden_keys = {"host_id", "hub_host", "server_ip", "room_name"}
    ipv4 = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
    checked = 0
    sources = list(ROOT.rglob("*.schema.json")) + list((ROOT / "examples" / "valid").glob("*.json"))
    for path in sorted(sources):
        value = load_json(path)
        overlap = forbidden_keys.intersection(_walk_keys(value))
        if overlap:
            raise ConformanceError(
                f"Host-bound field(s) {sorted(overlap)} in canonical source {path}"
            )
        text = path.read_text(encoding="utf-8")
        if "livekit" in text.lower() or ipv4.search(text):
            raise ConformanceError(
                f"transport/Host implementation detail in canonical source {path}"
            )
        checked += 1
    return checked


def check_traceability(schemas: dict[str, dict[str, Any]]) -> int:
    requirements = load_json(ROOT / "requirements" / "requirements.json")["requirements"]
    required_fields = {
        "requirement_id",
        "normative_text_ref",
        "owner",
        "schema_ids",
        "producer_tests",
        "consumer_tests",
        "simulator_vectors",
        "integration_tests",
        "hil_tests",
        "status",
        "waiver_reason",
        "waiver_expires_at",
    }
    ids: set[str] = set()
    for requirement in requirements:
        missing = required_fields - requirement.keys()
        if missing:
            raise ConformanceError(
                f"{requirement.get('requirement_id', '<unknown>')}: missing traceability fields "
                f"{sorted(missing)}"
            )
        requirement_id = requirement["requirement_id"]
        if requirement_id in ids:
            raise ConformanceError(f"duplicate requirement id: {requirement_id}")
        ids.add(requirement_id)
        mapped_tests = sum(
            len(requirement[key])
            for key in (
                "producer_tests",
                "consumer_tests",
                "simulator_vectors",
                "integration_tests",
                "hil_tests",
            )
        )
        if mapped_tests == 0:
            raise ConformanceError(f"{requirement_id}: requirement has no mapped test")
        if requirement["status"] not in {"planned", "covered", "waived"}:
            raise ConformanceError(f"{requirement_id}: invalid status")
        if requirement["status"] == "waived":
            if not requirement["waiver_reason"] or not requirement["waiver_expires_at"]:
                raise ConformanceError(f"{requirement_id}: waiver must be reasoned and expiring")
        elif (
            requirement["waiver_reason"] is not None or requirement["waiver_expires_at"] is not None
        ):
            raise ConformanceError(f"{requirement_id}: non-waived requirement carries waiver data")

    valid_coverage: set[tuple[str, str]] = set()
    for path in sorted((ROOT / "examples" / "valid").glob("*.json")):
        for case in load_json(path)["cases"]:
            valid_coverage.add((case["schema"], case["definition"]))
    for schema_id, schema in schemas.items():
        for definition in schema.get("$defs", {}):
            if (schema_id, definition) not in valid_coverage:
                raise ConformanceError(f"{schema_id}#/$defs/{definition}: no valid fixture")

    baseline = load_json(ROOT / "baseline" / "cross-repo-heads.v1.json")
    expected_repos = {entry["repo"] for entry in baseline["repositories"]}
    matrix = load_json(ROOT / "requirements" / "consumer-matrix.json")
    assigned_repos = {entry["repo"] for entry in matrix["participants"]}
    assigned_repos.update(entry["repo"] for entry in matrix["non_participants"])
    if expected_repos != assigned_repos:
        raise ConformanceError(
            f"producer/consumer ownership mismatch: missing={sorted(expected_repos - assigned_repos)}, "
            f"unknown={sorted(assigned_repos - expected_repos)}"
        )
    return len(requirements)


def check_state_vectors() -> int:
    host = load_json(ROOT / "state-vectors" / "host-relocation.json")
    required_unchanged = {
        "device_ref.device_instance_id",
        "device_ref.claim_generation",
        "device_ref.trust_epoch",
        "mount_revision",
        "assignment_generation",
        "operation_id",
    }
    if set(host["then"]["unchanged"]) != required_unchanged:
        raise ConformanceError("Host relocation oracle does not preserve every stable generation")
    if host["when"]["owner_root_changed"] or host["then"]["commissioning_state"] != "closed":
        raise ConformanceError("Host relocation oracle incorrectly enters commissioning")
    if host["given"]["operation_id"] != host["then"]["reconcile_operation_id"]:
        raise ConformanceError("Host relocation oracle changes operation identity")

    idempotency = load_json(ROOT / "state-vectors" / "idempotency.json")["vectors"]
    verdicts = {vector["vector_id"]: vector for vector in idempotency}
    if verdicts["DF-IDEM-SAME-ID-DIFFERENT-PAYLOAD"]["expected_problem"] != (
        "IDEMPOTENCY_CONFLICT"
    ):
        raise ConformanceError("idempotency conflict vector drifted")
    if verdicts["DF-IDEM-003"]["first_scope"][0] == verdicts["DF-IDEM-003"]["second_scope"][0]:
        raise ConformanceError("cross-Owner idempotency vector does not vary Owner scope")

    operation = load_json(ROOT / "state-vectors" / "operation-terminal.json")
    terminal = set(operation["terminal_states"])
    if any(source in terminal for source, _target in operation["allowed_transitions"]):
        raise ConformanceError("terminal operation state has an outgoing transition")
    if operation["delivery_acceptance_terminal"]:
        raise ConformanceError("delivery acceptance is incorrectly terminal")

    erase = load_json(ROOT / "state-vectors" / "device-local-erase.json")
    if erase["operation_type"] != "device-local.erase":
        raise ConformanceError("device-local erase operation type drifted")
    if set(erase["terminal_states"]) != {
        "acknowledged",
        "expired",
        "permanent-failure",
    }:
        raise ConformanceError("device-local erase terminal states drifted")
    if erase["delivery_acceptance_terminal"]:
        raise ConformanceError("device-local erase treats delivery as completion")
    erase_scenarios = {item["id"]: item for item in erase["scenarios"]}
    required_scenarios = {
        "online",
        "offline",
        "duplicate",
        "same-id-different-payload",
        "deadline",
        "permanent-failure",
        "restart",
        "old-generation",
        "host-relocation",
    }
    if set(erase_scenarios) != required_scenarios:
        raise ConformanceError("device-local erase scenario coverage drifted")
    if erase_scenarios["offline"]["platform_removal_blocked"]:
        raise ConformanceError("offline local erase incorrectly blocks platform removal")
    if erase_scenarios["duplicate"]["semantic_result"] != "replayed":
        raise ConformanceError("device-local erase replay semantics drifted")
    if erase_scenarios["same-id-different-payload"]["error"] != "IDEMPOTENCY_CONFLICT":
        raise ConformanceError("device-local erase idempotency conflict drifted")
    if erase_scenarios["deadline"]["late_ack_rewrites_terminal"]:
        raise ConformanceError("late device-local erase ACK rewrites a terminal result")
    if erase_scenarios["old-generation"]["new_claim_changed"]:
        raise ConformanceError("old-generation erase ACK mutates a newer claim")
    if erase_scenarios["host-relocation"]["operation_id_changes"]:
        raise ConformanceError("Host relocation changes device-local erase identity")

    rejoin = load_json(ROOT / "state-vectors" / "hardware-rejoin.json")
    incarnations = rejoin["incarnations"]
    rejoin_invariants = rejoin["invariants"]
    if len(incarnations) != 2 or incarnations[0]["device_instance_id"] == incarnations[1][
        "device_instance_id"
    ]:
        raise ConformanceError("hardware rejoin does not rotate the operational incarnation")
    if [item["claim_generation"] for item in incarnations] != [1, 2]:
        raise ConformanceError("hardware rejoin Claim generation is not monotonic")
    rejoin_true = {
        "device_instance_id_changes_after_physical_recovery",
        "claim_generation_monotonic_per_owner_and_base_identity",
        "old_claim_tombstone_retained",
        "hardware_identity_is_derived_from_issued_base_identity",
        # Erasing local storage ends the lineage rather than continuing it.
        # The factory secret that used to survive an erase is gone, so a wiped
        # device cannot prove it is the same board — and a platform that
        # correlated it anyway would be inheriting ownership from an
        # unauthenticated MAC.
        "local_erase_destroys_the_base_identity",
        "erased_device_rejoins_as_a_new_base_identity",
    }
    if any(rejoin_invariants[name] is not True for name in rejoin_true):
        raise ConformanceError("hardware rejoin positive invariant drifted")
    rejoin_false = {
        "hardware_identity_ref_changes",
        "old_request_can_mutate_new_claim",
        "old_operation_can_mutate_new_claim",
        "hardware_identity_from_operational_evidence_digest",
        "mac_is_device_instance_id",
        # A board type is a firmware declaration carried by the Manifest, which
        # a device may re-assert. Welding one into the permanent hardware
        # identity is how a Waveshare AMOLED board became a "box3" for good.
        "hardware_identity_is_operator_supplied",
        "hardware_identity_states_board_type",
        "device_may_report_its_own_base_identity",
        "revoked_base_identity_may_re_enter_without_a_fresh_voucher",
        "platform_auto_correlates_by_unauthenticated_mac",
    }
    if any(rejoin_invariants[name] is not False for name in rejoin_false):
        raise ConformanceError("hardware rejoin fencing invariant drifted")
    if rejoin["stable_hardware_identity_ref"] != _derived_hardware_identity_ref(
        load_json(ROOT / "golden" / "commissioning-voucher.json")["device_base_id"]
    ):
        raise ConformanceError("rejoin hardware identity is not the derived identity")

    commissioning = load_json(ROOT / "state-vectors" / "commissioning-runtime.json")
    invariants = commissioning["invariants"]
    required_true = {
        "single_writer",
        "callbacks_enqueue_only",
        "softap_uri_capacity_is_explicit",
        "transport_cleanup_claimed_exactly_once",
        "advertising_requires_transport_ready_evidence",
        "rollback_precedes_transport_stop",
        "radio_restore_follows_transport_stop",
        "legacy_connect_timeout_is_intent_only",
        "committed_completion_requires_station_route_ready",
        "admission_waits_for_station_route_ready",
        "pending_enrollment_query_uses_authority_clock",
        "stale_generation_is_ignored",
    }
    if any(invariants.get(name) is not True for name in required_true):
        raise ConformanceError("commissioning single-writer/readiness/cleanup invariant drifted")
    required_false = {
        "network_commit_before_owner_route_validation",
        "trust_activation_before_owner_route_validation",
        "transport_stop_before_controller_observes_terminal",
        "controller_route_release_before_terminal_ack",
    }
    if any(invariants.get(name) is not False for name in required_false):
        raise ConformanceError("commissioning transaction ordering invariant drifted")
    success = commissioning["success_sequence"]
    ordered = [
        "trust-staged",
        "network-candidate-staged",
        "wifi-connected",
        "owner-route-validated",
        "trust-and-network-committed",
        "controller-observed-terminal",
        "transport-stopped",
        "station-restore-commanded",
        "station-route-ready",
    ]
    if [success.index(item) for item in ordered] != sorted(success.index(item) for item in ordered):
        raise ConformanceError("commissioning success sequence is not transactionally ordered")
    return 6


def _derived_hardware_identity_ref(device_base_id: str) -> str:
    """Derive the one permanent identity ref of an issued base identity.

    Case and surrounding whitespace fold because the input is hex and a
    producer that reformats it must not fork one Body into two identity
    lineages; nothing else about the input survives, so an unverifiable claim
    (a board type, a vendor, a room) cannot ride along inside the identity. The
    input is always a base identity the Hub itself issued: a value the device
    chose could otherwise become permanent history simply by being well shaped.
    """

    canonical = device_base_id.strip().casefold()
    label = "eidolon-hardware-identity-v1"
    digest = hashlib.sha256((label + "\0" + canonical).encode()).hexdigest()
    return "hardware-" + digest


def check_commissioning_voucher() -> int:
    """Hold the issued-base-identity vector to its own arithmetic.

    The vector this replaced described a per-device factory secret that a
    firmware image and a Hub-side registry file both had to carry, byte for
    byte. Two ledgers for one fact drifted the way two ledgers do: a v1 registry
    entry welded an unverifiable board type into a permanent identity, and a
    rollback across that file's format left the Hub crash-looping 110 times.
    Neither failure has a carrier any more — the device carries nothing, and
    the Hub keeps no per-device file. What must not drift now is the binding:
    an issued base identity, one operational key, and a voucher that is worth
    nothing to anyone holding a different key.
    """

    vector = load_json(ROOT / "golden" / "commissioning-voucher.json")
    if vector["evidence_scheme"] != BASE_IDENTITY_EVIDENCE_SCHEME:
        raise ConformanceError("base identity evidence scheme drifted")
    if vector["base_identity_provenance"] != "minted":
        raise ConformanceError("hardware base identity must be minted, never derived from the device")

    spki_der = _b64url_decode(vector["operational_public_key"].removeprefix("p256-spki:"))
    digest = hashlib.sha256(spki_der).hexdigest()
    if vector["operational_spki_sha256"] != "sha256:" + digest:
        raise ConformanceError("operational SPKI fingerprint drifted")
    # Computed by the function the voucher, the instance id and the erase
    # ledger all take this value from, in both of the SPKI spellings the
    # contract carries — two spellings of this are two identities for one key.
    for spelling in (
        vector["operational_public_key"],
        vector["operational_public_key"].removeprefix("p256-spki:"),
    ):
        if operational_key_id(spelling) != vector["operational_spki_sha256"]:
            raise ConformanceError(
                "operational key id is not what the canonical function computes"
            )
    if vector["device_instance_id"] != "device-instance-" + digest:
        raise ConformanceError("device instance id is not the operational SPKI fingerprint")

    # The device may not choose this value, so the vector must show it being
    # derived from the issued base identity and from nothing else.
    for base_id, input_field, ref_field in (
        (
            vector["device_base_id"],
            "hardware_identity_derivation_input_utf8_with_nul_separator",
            "hardware_identity_ref",
        ),
        (
            vector["software_body_device_base_id"],
            "software_body_hardware_identity_derivation_input_utf8_with_nul_separator",
            "software_body_hardware_identity_ref",
        ),
    ):
        derivation_input = vector[input_field]
        if derivation_input != "eidolon-hardware-identity-v1\0" + base_id.casefold():
            raise ConformanceError("base identity derivation input drifted")
        if vector[ref_field] != _derived_hardware_identity_ref(
            base_id
        ) or vector[ref_field] != "hardware-" + hashlib.sha256(
            derivation_input.encode()
        ).hexdigest():
            raise ConformanceError("identity ref is not derived from the issued base identity")

    document = vector["evidence_document"]
    if document["device_base_id"] != vector["device_base_id"]:
        raise ConformanceError("evidence document states a different base identity")
    # Rebuilt by the function every producer calls. The device signs its own
    # copy and the Authority re-derives these bytes to verify, so a member
    # added, renamed or reordered is reported as an unverifiable proof rather
    # than as a document disagreement.
    if document != base_identity_evidence_document(
        device_base_id=vector["device_base_id"],
        device_instance_id=vector["device_instance_id"],
        operational_public_key=vector["operational_public_key"],
    ):
        raise ConformanceError(
            "evidence document is not what the canonical builder produces"
        )
    if set(document) != BASE_IDENTITY_EVIDENCE_FIELDS:
        raise ConformanceError("evidence document member set drifted")
    canonical = canonical_bytes(document)
    if canonical.decode() != vector["evidence_canonical_utf8"]:
        raise ConformanceError("base identity evidence JCS bytes drifted")
    if vector["wire_evidence"] != base_identity_evidence_wire(
        document=document, signature=vector["evidence_signature"]
    ):
        raise ConformanceError("base identity evidence wire framing drifted")
    if vector["evidence_digest"] != base_identity_evidence_digest(
        vector["wire_evidence"]
    ):
        raise ConformanceError("evidence digest is not the digest of the wire evidence")
    raw_signature = _b64url_decode(vector["evidence_signature"])
    if len(raw_signature) != 64:
        raise ConformanceError("base identity evidence signature is not raw ES256 r||s")
    public_key = serialization.load_der_public_key(spki_der)
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
        public_key.curve, ec.SECP256R1
    ):
        raise ConformanceError("base identity evidence operational key is not P-256")
    try:
        public_key.verify(
            encode_dss_signature(
                int.from_bytes(raw_signature[:32], "big"),
                int.from_bytes(raw_signature[32:], "big"),
            ),
            canonical,
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature as exc:
        raise ConformanceError("base identity evidence signature is invalid") from exc
    if vector["evidence_signature_encoding"] != (
        "ES256 raw r||s, 64 bytes, base64url without padding"
    ):
        raise ConformanceError(
            "base identity evidence signature encoding is not the one verified above"
        )

    # The voucher is recomputed from the two constants the vector names, not
    # read back from itself. A vector that merely restated its own token would
    # let the signing-key derivation change while the suite stayed green, and
    # the symptom of that is a 401 on every first commissioning with neither
    # side's intermediate value visible.
    voucher = vector["voucher"]
    if voucher["scheme"] != "hub-issued-commissioning-voucher-v1":
        raise ConformanceError("commissioning proof scheme drifted")
    claims = voucher["claims"]
    if claims["operational_spki_sha256"] != vector["operational_spki_sha256"]:
        raise ConformanceError("voucher is not bound to this operational key")
    if claims["device_base_id"] != vector["device_base_id"]:
        raise ConformanceError("voucher states a different base identity")
    if claims["jti"] != voucher["jti"] or claims["exp"] != voucher["expires_at_unix"]:
        raise ConformanceError("voucher claims disagree with the vector's own fields")
    if claims["purpose"] != COMMISSIONING_VOUCHER_PURPOSE:
        raise ConformanceError("voucher purpose claim drifted")
    # Rebuilt by the function Admin, Hub and the Kernel e2e all call, rather
    # than compared against a restatement of the claim set here. Nothing sends
    # these members between the two ends — the issuer signs its own copy and the
    # verifier requires the set it independently believes in — so a claim added,
    # renamed or dropped is otherwise reported as a bad signature at a device.
    if commissioning_voucher_claims(
        device_base_id=vector["device_base_id"],
        owner_domain_id=vector["owner_domain_id"],
        operational_spki_sha256=vector["operational_spki_sha256"],
        jti=voucher["jti"],
        expires_at_unix=voucher["expires_at_unix"],
        provenance=vector["base_identity_provenance"],
    ) != claims:
        raise ConformanceError(
            "voucher claims are not what the canonical builder produces"
        )
    if set(claims) != COMMISSIONING_VOUCHER_CLAIM_NAMES:
        raise ConformanceError("voucher claim member set drifted")
    if voucher["claim_names"] != sorted(COMMISSIONING_VOUCHER_CLAIM_NAMES):
        raise ConformanceError("published claim_names disagree with the claim set")
    if voucher["header"] != COMMISSIONING_VOUCHER_HEADER:
        raise ConformanceError("voucher header drifted")
    # Derived by the function Admin and Hub both call, not by a second spelling
    # of it here. A vector checked against its own restatement of the
    # derivation would stay green while every real caller moved underneath it.
    signing_key = derive_voucher_signing_key(
        bytes.fromhex(voucher["host_management_secret_hex"])
    )
    if signing_key.hex() != voucher["signing_key_hex"]:
        raise ConformanceError("voucher signing key derivation drifted")
    # The prose beside the bytes is held to them too: a reader who trusts the
    # description instead of recomputing must not be told a different rule.
    if voucher["signing_key_derivation"] != (
        "HKDF-SHA256(host management secret, salt=none, "
        f'info="{COMMISSIONING_VOUCHER_KEY_INFO.decode()}", L=32)'
    ):
        raise ConformanceError(
            "voucher signing key derivation prose disagrees with the derivation used"
        )
    header_canonical = canonical_bytes(voucher["header"])
    claims_canonical = canonical_bytes(claims)
    if header_canonical.decode() != voucher["header_canonical_utf8"]:
        raise ConformanceError("voucher header JCS bytes drifted")
    if claims_canonical.decode() != voucher["claims_canonical_utf8"]:
        raise ConformanceError("voucher claims JCS bytes drifted")
    signing_input = "{}.{}".format(
        base64.urlsafe_b64encode(header_canonical).rstrip(b"=").decode(),
        base64.urlsafe_b64encode(claims_canonical).rstrip(b"=").decode(),
    )
    if signing_input != voucher["signing_input"]:
        raise ConformanceError("voucher signing input framing drifted")
    # Signed by the canonical framing rather than a reconstruction of it, for
    # the same reason: the compact form is a contract, and a verifier that
    # re-derives it rejects any other member order.
    if voucher["compact"] != sign_commissioning_voucher(
        claims=claims, signing_key=signing_key
    ):
        raise ConformanceError("voucher signature drifted")
    if voucher["nonce_rule"] != "commissioning_proof.nonce MUST equal the voucher jti":
        raise ConformanceError("voucher nonce rule drifted")

    # The other accepted provenance. Unpinned, a verifier could quietly stop
    # accepting `derived-from-controller` and every suite would stay green while
    # no removed Body could ever return as itself.
    continuation = vector["voucher_derived_from_controller"]
    continuation_claims = continuation["claims"]
    if continuation_claims["base_identity_provenance"] != "derived-from-controller":
        raise ConformanceError("continuation voucher is not the other provenance")
    if continuation_claims != commissioning_voucher_claims(
        device_base_id=vector["device_base_id"],
        owner_domain_id=vector["owner_domain_id"],
        operational_spki_sha256=vector["operational_spki_sha256"],
        jti=continuation["jti"],
        expires_at_unix=voucher["expires_at_unix"],
        provenance="derived-from-controller",
    ):
        raise ConformanceError(
            "continuation voucher claims are not what the canonical builder produces"
        )
    if canonical_bytes(continuation_claims).decode() != continuation["claims_canonical_utf8"]:
        raise ConformanceError("continuation voucher claims JCS bytes drifted")
    if continuation["compact"] != sign_commissioning_voucher(
        claims=continuation_claims, signing_key=signing_key
    ):
        raise ConformanceError("continuation voucher signature drifted")
    if continuation["jti"] == voucher["jti"]:
        raise ConformanceError("the two vouchers must not share a one-shot jti")

    base_key = vector["enrolled_base_key"]
    if base_key["scheme"] != "enrolled-base-key-v1":
        raise ConformanceError("continuation proof scheme drifted")
    base_document = base_key["signing_document"]
    if base_document["nonce"] != base_key["nonce"]:
        raise ConformanceError("continuation proof nonce disagrees with its own document")
    base_canonical = canonical_bytes(base_document)
    if base_canonical.decode() != base_key["canonical_utf8"]:
        raise ConformanceError("continuation proof JCS bytes drifted")
    base_signature = _b64url_decode(base_key["proof"])
    if len(base_signature) != 64:
        raise ConformanceError("continuation proof is not raw ES256 r||s")
    try:
        public_key.verify(
            encode_dss_signature(
                int.from_bytes(base_signature[:32], "big"),
                int.from_bytes(base_signature[32:], "big"),
            ),
            base_canonical,
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature as exc:
        raise ConformanceError("continuation proof signature is invalid") from exc

    refusals = [entry["case"] for entry in vector["must_be_refused"]]
    if refusals != [
        "voucher bound to another operational key",
        "voucher replayed after its jti was consumed",
        "device reports a device_base_id the Hub never issued",
        "second base identity offered for an already bound operational key",
        "enrolled-base-key-v1 presented by a Revoked or Rejected base identity",
        "voucher whose base_identity_provenance is any other value",
        "voucher carrying a claim outside claim_names, or missing one",
    ]:
        raise ConformanceError("the refusals this vector exists to name drifted")

    refusal_fields = {"must_be_refused"}
    for index in range(len(vector["must_be_refused"])):
        refusal_fields |= {
            f"must_be_refused[{index}]",
            f"must_be_refused[{index}].case",
            f"must_be_refused[{index}].why",
        }
    require_field_inventory(
        vector,
        golden="commissioning-voucher",
        validated={
            "device_base_id",
            "base_identity_provenance",
            "hardware_identity_derivation_input_utf8_with_nul_separator",
            "hardware_identity_ref",
            "software_body_device_base_id",
            "software_body_hardware_identity_derivation_input_utf8_with_nul_separator",
            "software_body_hardware_identity_ref",
            "operational_public_key",
            "operational_spki_sha256",
            "device_instance_id",
            "evidence_scheme",
            "evidence_document",
            "evidence_document.device_base_id",
            "evidence_document.device_instance_id",
            "evidence_document.operational_public_key",
            "evidence_document.profile_id",
            "evidence_canonical_utf8",
            "evidence_signature_encoding",
            "evidence_signature",
            "wire_evidence",
            "evidence_digest",
            "owner_domain_id",
            "voucher",
            "voucher.scheme",
            "voucher.host_management_secret_hex",
            "voucher.signing_key_hex",
            "voucher.header",
            "voucher.header.alg",
            "voucher.header.typ",
            "voucher.header_canonical_utf8",
            "voucher.claims",
            "voucher.claims.base_identity_provenance",
            "voucher.claims.device_base_id",
            "voucher.claims.exp",
            "voucher.claims.jti",
            "voucher.claims.operational_spki_sha256",
            "voucher.claims.owner_domain_id",
            "voucher.claims.purpose",
            "voucher.claims_canonical_utf8",
            "voucher.signing_input",
            "voucher.compact",
            "voucher.jti",
            "voucher.expires_at_unix",
            "voucher.nonce_rule",
            "voucher.claim_names",
            "voucher_derived_from_controller",
            "voucher_derived_from_controller.claims",
            "voucher_derived_from_controller.claims.base_identity_provenance",
            "voucher_derived_from_controller.claims.device_base_id",
            "voucher_derived_from_controller.claims.exp",
            "voucher_derived_from_controller.claims.jti",
            "voucher_derived_from_controller.claims.operational_spki_sha256",
            "voucher_derived_from_controller.claims.owner_domain_id",
            "voucher_derived_from_controller.claims.purpose",
            "voucher_derived_from_controller.claims_canonical_utf8",
            "voucher_derived_from_controller.compact",
            "voucher_derived_from_controller.jti",
            "enrolled_base_key",
            "enrolled_base_key.scheme",
            "enrolled_base_key.signing_document",
            "enrolled_base_key.signing_document.contract",
            "enrolled_base_key.signing_document.device_base_id",
            "enrolled_base_key.signing_document.device_instance_id",
            "enrolled_base_key.signing_document.nonce",
            "enrolled_base_key.signing_document.owner_domain_id",
            "enrolled_base_key.canonical_utf8",
            "enrolled_base_key.proof",
            "enrolled_base_key.nonce",
        }
        | refusal_fields,
        descriptive={
            "vector_id",
            "supersedes",
            "why",
            "device_operational_scalar_hex",
            "voucher.signing_key_derivation",
            "voucher_derived_from_controller.why",
            "enrolled_base_key.when",
        },
    )
    return 1


def check_admission_credential() -> int:
    """Hold the shared credential implementation to the incident this file records.

    Admin mints and Hub reads through one SDK function, so the two cannot spell
    a claim differently any more. What that shared function cannot do is notice
    that it has stopped matching *this* file — and this file is the written
    record of a real outage: the removal path presented another Hub surface's
    vocabulary (``actor_ref`` as a bare string, ``owner_id``, ``roles``) and
    every device removal was refused with a 401 that never mentioned a
    credential, for months.

    Nothing read this file until now, and it had already drifted: the
    implementation emits an optional ``target_device_ref`` claim that the file
    did not list. That is what a vector with no reader does — it becomes a
    description of what the code used to do.
    """

    vector = load_json(ROOT / "golden" / "admission-credential.json")
    if (vector["header_scheme"], vector["algorithm"], vector["audience"]) != (
        "Bearer",
        "HS256",
        ADMISSION_AUDIENCE,
    ):
        raise ConformanceError("Admission credential vector names another scheme or audience")

    secret = b"conformance-admission-credential-secret-32+"
    stable = vector["stable_claims"]
    header = issue_admission_credential(
        AdmissionCredential(
            subject=stable["sub"],
            actor=ControllerActorRef.model_validate(stable["actor"]),
            owner_domain_id=OwnerDomainId(stable["owner_domain_id"]),
            business_owner_id=BusinessOwnerId(stable["business_owner_id"]),
            scopes=tuple(stable["scopes"]),
            intent_id=stable["intent_id"],
        ),
        secret=secret,
        ttl_seconds=300,
    )
    scheme, _, token = header.partition(" ")
    if scheme != vector["header_scheme"]:
        raise ConformanceError("minted Admission credential does not use the declared scheme")
    minted = jwt.decode(
        token, secret, algorithms=[vector["algorithm"]], audience=vector["audience"]
    )
    # The claim names actually put on the wire, held to the two lists this file
    # publishes. Drift in either direction is refused: a claim minted and not
    # listed, and a claim listed and not minted.
    # Required must all be minted; optional may be absent; nothing undeclared
    # may appear. Not an equality — that only holds when every optional claim
    # happens to be present, and would let this file omit an optional claim the
    # implementation can emit.
    declared = set(vector["required_claims"]) | set(vector["optional_claims"])
    if undeclared := set(minted) - declared:
        raise ConformanceError(
            f"Admission credential mints claims this vector does not name: {sorted(undeclared)}"
        )
    if missing := set(vector["required_claims"]) - set(minted):
        raise ConformanceError(
            f"Admission credential omits required claims: {sorted(missing)}"
        )
    # Every claim whose value does not depend on when it was minted has to have
    # a stated value here. Iterating whatever `stable_claims` happened to hold
    # meant a claim could be dropped from this file and nothing would ask for
    # it: `presenter` and `aud` were both deletable, and `presenter` is the one
    # that binds a credential to the party presenting it.
    timing = {"iat", "exp"}
    pinned = set(vector["required_claims"]) - timing
    if not pinned <= set(stable):
        raise ConformanceError(
            f"Admission vector states no value for {sorted(pinned - set(stable))}"
        )
    for name, expected in stable.items():
        if minted[name] != expected:
            raise ConformanceError(f"minted Admission claim {name} is not the stable value")

    reread = read_admission_credential(header, secret=secret)
    if (
        reread.subject != stable["sub"]
        or str(reread.owner_domain_id) != stable["owner_domain_id"]
        or str(reread.business_owner_id) != stable["business_owner_id"]
        or list(reread.scopes) != stable["scopes"]
    ):
        raise ConformanceError("Admission credential does not survive its own round trip")

    # The outage, replayed. This shape decoded as a JWT perfectly well; what
    # failed was the vocabulary, and it has to keep failing.
    # The exact vocabulary that failed, pinned name by name. Refusal alone does
    # not hold these: the shape is refused for several reasons at once, so any
    # single claim could be deleted from the record and it would still be
    # refused — and the record is the only place the wrong vocabulary is
    # written down.
    if set(vector["rejected_shape"]["claims"]) != {
        "sub", "presenter", "aud", "actor_ref", "owner_id", "roles", "scopes", "exp"
    }:
        raise ConformanceError("the recorded vocabulary of the 401 outage changed")
    rejected = jwt.encode(vector["rejected_shape"]["claims"], secret, algorithm=_ALGORITHM_NAME)
    try:
        read_admission_credential("Bearer " + rejected, secret=secret)
    except AdmissionCredentialError:
        pass
    else:
        raise ConformanceError(
            "the credential shape that refused every device removal is accepted again"
        )

    require_field_inventory(
        vector,
        golden="admission-credential",
        validated={
            "header_scheme", "algorithm", "audience", "required_claims",
            "optional_claims", "stable_claims",
            "rejected_shape", "rejected_shape.claims",
        }
        | {f"stable_claims.{name}" for name in stable}
        | {f"stable_claims.actor.{name}" for name in stable["actor"]}
        | {f"rejected_shape.claims.{name}" for name in vector["rejected_shape"]["claims"]},
        descriptive={"contract", "purpose", "rejected_shape.why"},
    )
    return 1 + len(vector["required_claims"])


def check_device_instance_derivation() -> int:
    """What a device instance id is derived from, and what may never derive one.

    The rule had four implementations and no vector. Each of Hub, the firmware,
    this SDK and a phone read it from prose; three of the four would hash a raw
    uncompressed point into a perfectly well-formed identity that no Authority
    has a record of, and the phone was the only one that refused. That failure
    has no crypto error and no signature mismatch — it surfaces as a device
    nobody recognises, on some boards and not others.
    """

    vector = load_json(ROOT / "golden" / "device-instance-derivation.json")
    if (vector["namespace"], vector["digest"]) != ("device-instance-", "sha256"):
        raise ConformanceError("device instance derivation names another rule")
    spki = _b64url_decode(vector["spki_der_base64url"])
    if len(spki) != vector["spki_der_length_bytes"]:
        raise ConformanceError("device instance derivation SPKI length disagrees with its bytes")
    if vector["device_instance_id"] != vector["namespace"] + hashlib.sha256(spki).hexdigest():
        raise ConformanceError("device instance id is not the SPKI digest this vector states")
    # Every accepted spelling of one key is one device. The prefixed and bare
    # forms both occur in the contract, and a consumer that reads only one of
    # them derives two identities for a single key.
    for spelling in vector["accepted_spellings"]:
        if derive_device_instance_id(spelling) != vector["device_instance_id"]:
            raise ConformanceError(f"accepted spelling derives another device: {spelling[:24]}")
    for case in vector["must_refuse"]:
        try:
            derived = derive_device_instance_id(case["encoded"])
        except ValueError:
            continue
        raise ConformanceError(
            f"device instance derivation accepted {case['case']}: {derived}"
        )
    # The point carried inside the SPKI is the same key, so the refusal above is
    # about encoding rather than about a different key — and the digest it would
    # have produced is recorded so a consumer can recognise it in the wild.
    raw_point = next(
        case for case in vector["must_refuse"] if case["case"] == "raw-uncompressed-point"
    )
    if _b64url_decode(raw_point["encoded"]) != spki[-raw_point["length_bytes"]:]:
        raise ConformanceError("the refused point is not the key this vector derives from")
    if raw_point["digest_if_wrongly_hashed"] == vector["device_instance_id"]:
        raise ConformanceError("the wrongly-hashed digest cannot equal the correct one")
    if raw_point["digest_if_wrongly_hashed"] != vector["namespace"] + hashlib.sha256(
        _b64url_decode(raw_point["encoded"])
    ).hexdigest():
        raise ConformanceError("recorded wrong digest is not what hashing the point produces")
    require_field_inventory(
        vector,
        golden="device-instance-derivation",
        validated={
            "namespace", "digest", "operational_public_key", "spki_der_base64url",
            "spki_der_length_bytes", "device_instance_id", "accepted_spellings",
            "must_refuse",
        }
        | {f"must_refuse[{index}]" for index in range(len(vector["must_refuse"]))}
        | {
            f"must_refuse[{index}].{field}"
            for index, case in enumerate(vector["must_refuse"])
            for field in ("case", "encoded", "length_bytes")
        }
        | {
            f"must_refuse[{index}].digest_if_wrongly_hashed"
            for index, case in enumerate(vector["must_refuse"])
            if "digest_if_wrongly_hashed" in case
        },
        descriptive={"vector_id", "purpose", "derived_from"}
        | {
            f"must_refuse[{index}].why"
            for index in range(len(vector["must_refuse"]))
        },
    )
    return 1 + len(vector["must_refuse"])


def check_p1_exit_evidence() -> int:
    evidence = load_json(ROOT / "evidence" / "p1-host-independence.json")
    if evidence["scope"] != (
        "P1 Host-independent addressing only; no P2-P4 authority semantics are claimed"
    ):
        raise ConformanceError("P1 evidence overclaims its authority scope")

    topologies = {item["name"]: item for item in evidence["topologies"]}
    required_topologies = {"single-host", "host-relocated", "host-loss-recovered"}
    if set(topologies) != required_topologies or not all(
        item["passed"] is True for item in topologies.values()
    ):
        raise ConformanceError("P1 evidence does not cover all required topology fixtures")

    host_a = evidence["host_a"]
    host_b = evidence["host_b"]
    if host_b["directory_revision"] <= host_a["directory_revision"]:
        raise ConformanceError("P1 Host B directory revision does not advance")
    for host in (host_a, host_b):
        if host["deployment_status"] != "activated" or host["application_ready"] is not True:
            raise ConformanceError("P1 Host deployment was not healthy and activated")
        if host["service_restart_count"] != 0:
            raise ConformanceError("P1 Host services restarted during acceptance")
        if host["device_accepted_directory_revision"] != host["directory_revision"]:
            raise ConformanceError("device did not accept the deployed Owner directory revision")
        if host["device_operational_ready"] is not True:
            raise ConformanceError("device did not reach confirmed operational readiness")
    if host_a["admission_uri"] == host_b["admission_uri"]:
        raise ConformanceError("P1 Host relocation evidence does not move the Admission endpoint")
    if host_a["device_control_uri"] == host_b["device_control_uri"]:
        raise ConformanceError("P1 Host relocation evidence does not move Device Control endpoint")
    owner_id = evidence["owner_identity"]["owner_domain_id"]
    expected_audiences = [
        f"{owner_id}:admission",
        f"{owner_id}:device-control",
    ]
    if (
        host_a["logical_audiences"] != expected_audiences
        or host_b["logical_audiences"] != expected_audiences
    ):
        raise ConformanceError("P1 Host move changed logical Authority addressing")

    owner = evidence["owner_identity"]
    expected_public_files = {
        "authority_signing_certificate.pem",
        "owner_domain_descriptor.json",
        "owner_domain_root_ca.pem",
    }
    if set(owner["runtime_public_files"]) != expected_public_files:
        raise ConformanceError("Owner runtime directory contains an unexpected artifact set")
    if owner["runtime_contains_directory_signing_private_key"] is not False:
        raise ConformanceError("Host runtime can access the Owner directory signing private key")

    device = evidence["device"]
    constraints = evidence["hil_constraints"]
    kernel_projection = device["p1_preserved_kernel_projection"]
    if (
        kernel_projection["mount_revision"] < 1
        or kernel_projection["active"] is not True
        or not kernel_projection["attached_companion_id"]
        or not (
            kernel_projection["updated_at"]
            < host_a["activation_receipt_observed_at"]
            < host_b["activation_receipt_observed_at"]
        )
    ):
        raise ConformanceError("Kernel Mount projection was not stable across Host relocation")
    required_false = {
        "entered_commissioning_during_authority_move": device[
            "entered_commissioning_during_authority_move"
        ],
        "nvs_erased": device["nvs_erased"],
    }
    if any(value is not False for value in required_false.values()):
        raise ConformanceError("Host relocation changed commissioning or erased device state")
    required_true = {
        "commissioning_was_not_repeated_for_host_move",
        "device_claim_was_not_recreated",
        "mount_or_assignment_was_not_mutated",
        "nvs_was_not_erased",
        "production_device_control_was_not_implemented",
    }
    if any(constraints.get(name) is not True for name in required_true):
        raise ConformanceError("P1 HIL boundary or preserved-state assertion is missing")

    storage = evidence["durable_trust_storage"]
    if storage["default_nvs_contains_owner_trust_keys"] is not False:
        raise ConformanceError("legacy shared NVS still owns active Owner trust")
    if (
        set(storage["owner_trust_slots"]) != {"ot0", "ot1"}
        or storage["active_slot_pointer_present"] is not True
    ):
        raise ConformanceError("durable Owner trust does not have two-slot publication evidence")

    sha256_hex = re.compile(r"^[0-9a-f]{64}$")
    digests = [
        owner["owner_root_certificate_sha256"],
        owner["authority_signing_certificate_sha256"],
        host_b["release_bundle_sha256"],
        host_b["descriptor_sha256"],
        storage["default_nvs_dump_sha256"],
        storage["owner_trust_dump_sha256"],
    ]
    if any(sha256_hex.fullmatch(value) is None for value in digests):
        raise ConformanceError("P1 evidence contains a malformed SHA-256 digest")
    if len(evidence["release_source_heads"]) != 8 or any(
        re.fullmatch(r"[0-9a-f]{40}", value) is None
        for value in evidence["release_source_heads"].values()
    ):
        raise ConformanceError("P1 release source set is incomplete or malformed")
    return 1


def run() -> dict[str, int]:
    schemas, registry = _load_schemas()
    return {
        "schemas": len(schemas),
        "fixtures": check_fixtures(schemas, registry),
        "canonical_vectors": check_canonical_vectors(),
        "es256_vectors": check_es256_vectors(),
        "device_local_erase_vectors": check_device_local_erase_vector(),
        "device_delivery_vectors": check_device_delivery_vector(),
        "device_manifest_vectors": check_device_manifest_vector(),
        "claim_revoke_vectors": check_claim_revoke_vector(),
        "owner_directory_vectors": check_owner_directory_vector(),
        "setup_descriptor_vectors": check_setup_descriptor_vector(schemas, registry),
        "hpke_vectors": check_hpke_vector(),
        "claim_grant_aad_checks": check_claim_grant_aad(),
        "claim_grant_wire_checks": check_claim_grant_wire_envelope(),
        "claim_grant_proof_checks": check_claim_grant_proof_vectors(),
        "device_control_proof_checks": check_device_control_proof_vectors(),
        "livekit_session_binding_checks": check_livekit_session_binding(),
        "device_configuration_response_checks": check_device_configuration_response(
            schemas, registry
        ),
        "claim_event_stream_vectors": check_admission_event_stream(),
        "protocomm_vectors": check_protocomm_framing(),
        "commissioning_voucher": check_commissioning_voucher(),
        "profiles": check_profile(),
        "host_independent_sources": check_host_independence(),
        "requirements": check_traceability(schemas),
        "state_vectors": check_state_vectors(),
        "admission_credential": check_admission_credential(),
        "device_instance_derivation": check_device_instance_derivation(),
        "p1_exit_evidence": check_p1_exit_evidence(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print a machine-readable result")
    args = parser.parse_args()
    try:
        result = run()
    except (ConformanceError, KeyError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        else:
            print(f"device-foundation-v1 conformance: FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, **result}, sort_keys=True))
    else:
        summary = ", ".join(f"{key}={value}" for key, value in result.items())
        print(f"device-foundation-v1 conformance: PASS ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
