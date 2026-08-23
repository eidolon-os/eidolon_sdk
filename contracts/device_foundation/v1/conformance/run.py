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
    vectors = load_json(ROOT / "golden" / "canonical-vectors.json")["vectors"]
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
    vectors = load_json(ROOT / "golden" / "es256-vectors.json")["vectors"]
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
    ciphertext = AESGCM(key).encrypt(
        bytes.fromhex(encryption["nonce"]),
        bytes.fromhex(encryption["plaintext"]),
        bytes.fromhex(encryption["aad"]),
    )
    if ciphertext.hex() != encryption["ciphertext"]:
        raise ConformanceError("RFC 9180 AES-128-GCM ciphertext mismatch")
    return 1


def check_claim_grant_aad() -> int:
    vector = load_json(ROOT / "golden" / "claim-grant-aad.json")
    aad = canonical_bytes(vector["aad"])
    if hashlib.sha256(aad).hexdigest() != vector["canonical_aad_sha256"]:
        raise ConformanceError("ClaimGrant AAD canonical digest mismatch")
    key = bytes.fromhex(vector["test_key"])
    nonce = bytes.fromhex(vector["test_nonce"])
    plaintext = bytes.fromhex(vector["plaintext"])
    ciphertext = bytes.fromhex(vector["ciphertext"])
    if AESGCM(key).decrypt(nonce, ciphertext, aad) != plaintext:
        raise ConformanceError("ClaimGrant AAD positive decrypt mismatch")
    for field in vector["mutate_each_field_must_fail"]:
        mutated = copy.deepcopy(vector["aad"])
        value = mutated[field]
        mutated[field] = value + "-mutated" if isinstance(value, str) else value + 1
        try:
            AESGCM(key).decrypt(nonce, ciphertext, canonical_bytes(mutated))
        except InvalidTag:
            continue
        raise ConformanceError(f"ClaimGrant AAD mutation did not fail: {field}")
    return 1 + len(vector["mutate_each_field_must_fail"])


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
    return 5


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
        "owner_directory_vectors": check_owner_directory_vector(),
        "hpke_vectors": check_hpke_vector(),
        "claim_grant_aad_checks": check_claim_grant_aad(),
        "protocomm_vectors": check_protocomm_framing(),
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
