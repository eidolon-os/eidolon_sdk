from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from eidolon_sdk.device_foundation.v1 import (
    DeliverEnvelope,
    DeliveryAcceptance,
    DeviceEvidenceEnvelope,
    DeviceLocalEraseAck,
    DeviceLocalEraseCommand,
)


ROOT = Path(__file__).resolve().parents[2] / "contracts" / "device_foundation" / "v1"


def _golden() -> dict[str, object]:
    return json.loads((ROOT / "golden" / "device-delivery.json").read_text())


def test_delivery_binding_round_trip_and_nested_erase_contract() -> None:
    golden = _golden()
    envelope = DeliverEnvelope.model_validate(golden["deliver"])
    command = DeviceLocalEraseCommand.model_validate(envelope.payload)
    assert envelope.kind == "operation"
    assert command.operation_id == envelope.message_id
    assert command.device_ref == envelope.device_ref
    assert command.deadline == envelope.deadline
    assert envelope.model_dump(mode="json") == golden["deliver"]


def test_delivery_acceptance_cannot_claim_execution_and_evidence_is_signed() -> None:
    golden = _golden()
    acceptance = DeliveryAcceptance.model_validate(golden["acceptance"])
    evidence = DeviceEvidenceEnvelope.model_validate(golden["evidence"])
    ack = DeviceLocalEraseAck.model_validate(evidence.payload)
    assert acceptance.state == "accepted"
    assert acceptance.adapter_code is None
    assert ack.device_signature
    assert ack.operation_id == evidence.message_id
    assert ack.device_ref == evidence.device_ref
    with pytest.raises(ValidationError, match="Extra inputs"):
        DeliveryAcceptance.model_validate(
            {**golden["acceptance"], "terminal_result": "erased"}
        )


def test_rejected_delivery_requires_stable_adapter_code() -> None:
    with pytest.raises(ValidationError, match="adapter_code"):
        DeliveryAcceptance(
            delivery_attempt_id="attempt_01",
            state="rejected",
            adapter_code=None,
        )


def test_device_evidence_envelope_rejects_adapter_terminal_verdict() -> None:
    evidence = _golden()["evidence"]
    with pytest.raises(ValidationError, match="Extra inputs"):
        DeviceEvidenceEnvelope.model_validate(
            {**evidence, "adapter_terminal_result": "erased"}
        )


def test_generated_python_surface_exports_delivery_bindings() -> None:
    namespace: dict[str, object] = {}
    exec((ROOT / "generated/python/device_foundation_v1.py").read_text(), namespace)
    assert {
        "DeliverEnvelope",
        "DeliveryAcceptance",
        "DeviceEvidenceEnvelope",
    } <= set(namespace)


def test_generated_dart_delivery_bindings_parse_golden(tmp_path: Path) -> None:
    generated = (ROOT / "generated/dart/device_foundation_v1.dart").as_uri()
    golden = _golden()
    script = tmp_path / "delivery_probe.dart"
    script.write_text(
        f"import 'dart:convert'; import '{generated}'; void main() {{"
        f"final d=jsonDecode(r'''{json.dumps(golden['deliver'])}''') as Map<String,dynamic>;"
        f"final a=jsonDecode(r'''{json.dumps(golden['acceptance'])}''') as Map<String,dynamic>;"
        f"final e=jsonDecode(r'''{json.dumps(golden['evidence'])}''') as Map<String,dynamic>;"
        "DeliverEnvelopeV1.fromJson(d); DeliveryAcceptanceV1.fromJson(a);"
        "DeviceEvidenceEnvelopeV1.fromJson(e);"
        "a['terminal_result']='erased'; try { DeliveryAcceptanceV1.fromJson(a);"
        "throw StateError('accepted adapter verdict'); } on FormatException { } }",
        encoding="utf-8",
    )
    completed = subprocess.run(["dart", "run", str(script)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_generated_cpp_delivery_surface_compiles(tmp_path: Path) -> None:
    source = tmp_path / "delivery_probe.cc"
    source.write_text(
        '#include "device_foundation_v1_generated.h"\n'
        "int main(){ using namespace eidolon::device_foundation::v1; "
        "DeliverEnvelope d; DeliveryAcceptance a; DeviceEvidenceEnvelope e; "
        "d.kind=DeliveryKind::Operation; a.state=DeliveryAcceptanceState::Accepted; "
        "return d.delivery_attempt_id.size()+a.adapter_code.size()+e.message_id.size(); }\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "c++",
            "-std=c++20",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-fsyntax-only",
            str(source),
            "-I",
            str(ROOT / "generated/cpp"),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
