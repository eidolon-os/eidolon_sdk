from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.audit import AuditEnvelope


def _event() -> AuditEnvelope:
    return AuditEnvelope(
        event_id="audit-schema-1",
        producer="eidolon-data",
        producer_seq=1,
        category="governance",
        owner_id="owner-1",
        subject_type="companion",
        subject_id="companion-1",
        action="companion.created",
        occurred_at=datetime.now(UTC),
    )


def test_audit_envelope_matches_normative_json_schema() -> None:
    schema_path = Path(__file__).parents[2] / "contracts/audit/envelope.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        _event().model_dump(mode="json", exclude_none=False)
    )


def test_audit_contract_is_strict_and_immutable() -> None:
    event = _event()

    with pytest.raises(ValidationError):
        event.action = "changed"  # type: ignore[misc]


def test_audit_contract_has_no_second_principal_or_synthetic_actor() -> None:
    schema_path = Path(__file__).parents[2] / "contracts/audit/envelope.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert "actor_type" not in AuditEnvelope.model_fields
    assert "actor_id" not in AuditEnvelope.model_fields
    assert "actor_type" not in schema["properties"]
    assert "actor_id" not in schema["properties"]
    assert "actor_type" not in schema["required"]
