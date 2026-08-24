from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from eidolon_sdk.device_foundation.v1 import (
    ClaimActivatedEvent,
    ClaimEventCursor,
    ClaimEventPage,
    ClaimEventStreamItem,
    ClaimGrant,
    ClaimGrantAAD,
    ClaimGrantWireEnvelope,
    ClaimRevokedEvent,
    CollectClaimGrantResult,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "device_foundation" / "v1"


def _case(path: str, case_id: str) -> dict[str, object]:
    cases = json.loads((CONTRACT / path).read_text())["cases"]
    return next(case["value"] for case in cases if case["case_id"] == case_id)


def _activated() -> dict[str, object]:
    return _case("examples/valid/delivery-and-events.json", "DF-EVENT-CLAIM-ACTIVATED-VALID")


def _revoked() -> dict[str, object]:
    return _case("examples/valid/delivery-and-events.json", "DF-EVENT-CLAIM-REVOKED-VALID")


def test_python_generated_surface_exports_all_consumer_objects() -> None:
    namespace: dict[str, object] = {}
    exec((CONTRACT / "generated/python/device_foundation_v1.py").read_text(), namespace)
    expected = {
        "CommandEnvelope", "CommandResult", "DeviceProblem", "RevokeClaim",
        "RevokeClaimResult",
        "CreateEnrollment", "CreateEnrollmentResult", "DecideEnrollment",
        "DecideEnrollmentResult", "CollectClaimGrant", "CollectClaimGrantResult",
        "AckClaimGrant", "AckClaimGrantResult", "EnrollmentProposal",
        "ApprovalDecision", "ClaimGrant", "GrantAck", "ClaimRecord",
        "ClaimGrantAAD", "ClaimGrantWireEnvelope", "EnrollmentProposalQuery",
        "EnrollmentProposalPage", "EnrollmentRecoveryProjection", "ClaimQuery",
        "ClaimPage", "ClaimActivatedEvent", "ClaimRevokedEvent",
        "ClaimEventCursor", "ClaimEventStreamItem", "ClaimEventPage",
    }
    assert expected <= set(namespace)


@pytest.mark.parametrize("field", ["source", "dataschema", "audience", "subject", "ownerdomainid"])
def test_claim_event_metadata_and_identity_fail_closed(field: str) -> None:
    value = _activated()
    value[field] = {
        "source": "urn:eidolon:host:pi5",
        "dataschema": "https://contracts.eidolon.live/wrong.json",
        "audience": "host-specific-reader",
        "subject": "device-instances/another_device",
        "ownerdomainid": "owner-domain_other",
    }[field]
    with pytest.raises(ValidationError):
        ClaimActivatedEvent.model_validate(value)


def test_claim_event_unknown_field_fails_closed() -> None:
    value = _revoked()
    value["stream_position"] = 4
    with pytest.raises(ValidationError, match="Extra inputs"):
        ClaimRevokedEvent.model_validate(value)


def test_claim_stream_position_is_transport_only_and_pages_are_contiguous() -> None:
    event = ClaimRevokedEvent.model_validate(_revoked())
    first = ClaimEventStreamItem(stream_position=1, event=event)
    page = ClaimEventPage(
        requested_after=ClaimEventCursor(stream_position=0),
        events=(first,),
        next_cursor=ClaimEventCursor(stream_position=1),
        high_watermark=1,
        observed_at="2026-08-18T00:05:00Z",
    )
    assert "stream_position" not in event.model_dump(mode="json")
    assert page.next_cursor.stream_position == 1
    with pytest.raises(ValidationError, match="gap or duplicate"):
        ClaimEventPage(
            requested_after=ClaimEventCursor(stream_position=0),
            events=(ClaimEventStreamItem(stream_position=2, event=event),),
            next_cursor=ClaimEventCursor(stream_position=2),
            high_watermark=2,
            observed_at="2026-08-18T00:05:00Z",
        )


def test_claim_grant_wire_envelope_exposes_pre_open_aad_and_matches_plaintext() -> None:
    envelope_value = json.loads(
        (CONTRACT / "golden/claim-grant-wire-envelope.json").read_text()
    )["envelope"]
    envelope = ClaimGrantWireEnvelope.model_validate(envelope_value)
    result = CollectClaimGrantResult.model_validate(
        {"grant_id": "grant_01", "wire_envelope": envelope_value,
         "expires_at": "2026-08-18T00:10:00Z", "approval_decision_id": "decision_01"}
    )
    assert result.wire_envelope.aad.owner_domain_id.root == "owner-domain_01"
    grant = ClaimGrant.model_validate(
        _case("examples/valid/admission.json", "DF-ADMISSION-CLAIM-GRANT-VALID")
    )
    envelope.aad.assert_matches_grant(grant)
    bad = ClaimGrantAAD.model_validate(
        {**envelope.aad.model_dump(mode="json"), "claim_generation": 99}
    )
    with pytest.raises(ValueError, match="does not match"):
        bad.assert_matches_grant(grant)


def test_dart_generated_binding_parses_envelope_and_rejects_unknown(tmp_path: Path) -> None:
    generated = (CONTRACT / "generated/dart/device_foundation_v1.dart").as_uri()
    envelope = json.loads(
        (CONTRACT / "golden/claim-grant-wire-envelope.json").read_text()
    )["envelope"]
    script = tmp_path / "probe.dart"
    script.write_text(
        f"import 'dart:convert'; import '{generated}'; void main() {{"
        f"final v=jsonDecode(r'''{json.dumps(envelope)}''') as Map<String,dynamic>;"
        "ClaimGrantWireEnvelopeV1.fromJson(v); v['unknown']=true;"
        "try { ClaimGrantWireEnvelopeV1.fromJson(v); throw StateError('accepted'); }"
        "on FormatException { } }",
        encoding="utf-8",
    )
    completed = subprocess.run(["dart", "run", str(script)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_cpp_generated_consumer_surface_compiles(tmp_path: Path) -> None:
    source = tmp_path / "probe.cc"
    source.write_text(
        '#include "device_foundation_v1_generated.h"\n'
        "int main(){ using namespace eidolon::device_foundation::v1; "
        "ClaimGrantWireEnvelope envelope; ClaimEventPage page; EnrollmentProposalQuery query; "
        "return IsValid(envelope) || page.high_watermark || query.limit; }\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", str(source),
         "-I", str(CONTRACT / "generated/cpp")], capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
