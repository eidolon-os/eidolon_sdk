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
from pathlib import Path
from typing import Any

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
            "canonical_aad_sha256", "test_aead", "test_key", "test_nonce",
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
        "claim_generation_monotonic_per_owner_and_hardware",
        "old_claim_tombstone_retained",
        "hardware_identity_is_derived_from_verified_hardware_lookup",
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
    }
    if any(rejoin_invariants[name] is not False for name in rejoin_false):
        raise ConformanceError("hardware rejoin fencing invariant drifted")
    if rejoin["stable_hardware_identity_ref"] != _derived_hardware_identity_ref(
        load_json(ROOT / "golden" / "development-commissioning-identity.json")[
            "hardware_lookup_id"
        ]
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


def _derived_hardware_identity_ref(hardware_lookup_id: str) -> str:
    """Derive the one permanent hardware identity of a verified lookup id.

    Case and surrounding whitespace fold because a MAC address is hex and a
    firmware that reformats it must not fork one board into two identity
    lineages; nothing else about the input survives, so an unverifiable claim
    (a board type, a vendor, a room) cannot ride along inside the identity.
    """

    canonical = hardware_lookup_id.strip().casefold()
    label = "eidolon-hardware-identity-v1"
    digest = hashlib.sha256((label + "\0" + canonical).encode()).hexdigest()
    return "hardware-" + digest


def check_development_commissioning_identity() -> int:
    vector = load_json(ROOT / "golden" / "development-commissioning-identity.json")
    # A development registry entry pre-shares a setup secret and states nothing
    # else. It used to carry a hand-typed hardware_identity_ref, and a
    # Waveshare ESP32-S3-Touch-AMOLED board was admitted as
    # "hardware-box3-1cdbd47aef0c": an unverifiable board type welded into an
    # identity that outlives every Claim of that hardware.
    if vector["profile_id"] != "eidolon-development-hmac-commissioning-v2":
        raise ConformanceError("development commissioning registry profile drifted")
    if vector["registry_entry_fields"] != ["setup_secret"]:
        raise ConformanceError("development registry entry may only pre-share a secret")
    derivation_input = vector["hardware_identity_derivation_input_utf8_with_nul_separator"]
    if derivation_input != "eidolon-hardware-identity-v1\0" + vector[
        "hardware_lookup_id"
    ].casefold():
        raise ConformanceError("hardware identity derivation input drifted")
    if vector["hardware_identity_ref"] != _derived_hardware_identity_ref(
        vector["hardware_lookup_id"]
    ) or vector["hardware_identity_ref"] != "hardware-" + hashlib.sha256(
        derivation_input.encode()
    ).hexdigest():
        raise ConformanceError("hardware identity is not derived from the verified lookup id")
    canonical = canonical_bytes(vector["evidence_document"])
    if canonical.decode() != vector["evidence_canonical_utf8"]:
        raise ConformanceError("development evidence JCS bytes drifted")
    if vector["wire_evidence"] != (
        vector["evidence_canonical_utf8"] + "." + vector["evidence_signature"]
    ):
        raise ConformanceError("development evidence wire framing drifted")
    spki_der = _b64url_decode(vector["operational_public_key"].removeprefix("p256-spki:"))
    digest = hashlib.sha256(spki_der).hexdigest()
    if vector["operational_spki_sha256"] != "sha256:" + digest:
        raise ConformanceError("operational SPKI fingerprint drifted")
    if vector["device_instance_id"] != "device-instance-" + digest:
        raise ConformanceError("device instance id is not the operational SPKI fingerprint")
    raw_signature = _b64url_decode(vector["evidence_signature"])
    if len(raw_signature) != 64:
        raise ConformanceError("development evidence signature is not raw ES256 r||s")
    public_key = serialization.load_der_public_key(spki_der)
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
        public_key.curve, ec.SECP256R1
    ):
        raise ConformanceError("development evidence operational key is not P-256")
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
        raise ConformanceError("development evidence signature is invalid") from exc
    if vector["evidence_signature_encoding"] != (
        "ES256 raw r||s, 64 bytes, base64url without padding"
    ):
        raise ConformanceError(
            "development evidence signature encoding is not the one verified above"
        )
    # The HMAC input is composed here rather than taken as given.
    #
    # It used to be read straight out of the vector, so the four parts the
    # vector says it is built from were held to nothing: `commissioning_nonce`
    # and `owner_domain_id` could each say one thing while the string encoded
    # another, and both could be deleted outright with this suite still green.
    # Hub composes this from its own parts, so a vector that disagrees would
    # have sent whoever debugged it after Hub rather than after the vector —
    # and the symptom is `401 commissioning proof is invalid`, with neither
    # side's intermediate value visible.
    composed_hmac_input = "\0".join(
        [
            vector["hardware_lookup_id"],
            vector["device_instance_id"],
            vector["owner_domain_id"],
            vector["commissioning_nonce"],
        ]
    )
    if vector["hmac_input_utf8_with_nul_separators"] != composed_hmac_input:
        raise ConformanceError(
            "commissioning HMAC input is not composed of the parts the vector names"
        )
    setup_secret = _b64url_decode(vector["setup_secret_base64url"])
    expected_proof = base64.urlsafe_b64encode(
        hmac.new(
            setup_secret,
            vector["hmac_input_utf8_with_nul_separators"].encode(),
            hashlib.sha256,
        ).digest()
    ).rstrip(b"=").decode()
    if not hmac.compare_digest(expected_proof, vector["commissioning_proof"]):
        raise ConformanceError("development commissioning HMAC vector drifted")
    require_field_inventory(
        vector,
        golden="development-commissioning-identity",
        validated={
            "profile_id",
            "hardware_lookup_id",
            "hardware_identity_derivation_input_utf8_with_nul_separator",
            "hardware_identity_ref",
            "operational_public_key",
            "operational_spki_sha256",
            "device_instance_id",
            "evidence_document",
            "evidence_document.device_instance_id",
            "evidence_document.hardware_lookup_id",
            "evidence_document.operational_public_key",
            "evidence_document.profile_id",
            "evidence_canonical_utf8",
            "evidence_signature_encoding",
            "evidence_signature",
            "wire_evidence",
            "commissioning_nonce",
            "owner_domain_id",
            "hmac_input_utf8_with_nul_separators",
            "setup_secret_base64url",
            "commissioning_proof",
            "registry_entry_fields",
        },
        descriptive={"vector_id"},
    )
    return 1


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
        "claim_revoke_vectors": check_claim_revoke_vector(),
        "owner_directory_vectors": check_owner_directory_vector(),
        "setup_descriptor_vectors": check_setup_descriptor_vector(schemas, registry),
        "hpke_vectors": check_hpke_vector(),
        "claim_grant_aad_checks": check_claim_grant_aad(),
        "claim_grant_wire_checks": check_claim_grant_wire_envelope(),
        "claim_event_stream_vectors": check_admission_event_stream(),
        "protocomm_vectors": check_protocomm_framing(),
        "development_commissioning_identity": check_development_commissioning_identity(),
        "profiles": check_profile(),
        "host_independent_sources": check_host_independence(),
        "requirements": check_traceability(schemas),
        "state_vectors": check_state_vectors(),
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
