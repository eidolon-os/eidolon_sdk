"""The Mission Control Local API contract, held to its own schemas.

Three kinds of drift are guarded here, because all three are silent:

* a golden payload that no longer validates — the shape moved without the
  examples moving with it;
* a schema enum that no longer matches the Python vocabulary this package
  exports — the two would then disagree about what a legal value is, and the
  producer and the consumer would each be right;
* an event vocabulary that stopped being the audit envelope's. The projection is
  *of* an audit event; the moment it invents its own word for "what happened",
  one fact has two taxonomies.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from eidolon_sdk.biz.contracts import mission_control as mc

_ROOT = Path(__file__).resolve().parents[2]
_V1 = _ROOT / "contracts/local_api/v1"
_AUDIT = _ROOT / "contracts/audit/envelope.schema.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    """Every contract resolved from this checkout, never from the network.

    The schemas reference each other and the audit envelope by declared $id.
    That is the point — the shared vocabularies are referenced, not copied — but
    it means a validator left to its own devices would try to fetch
    https://eidolon.dev/... and a test that needs the internet to check a
    contract is a test that fails for reasons unrelated to the contract.
    """

    resources = []
    for path in (
        _AUDIT,
        _V1 / "mission-control-event.schema.json",
        _V1 / "mission-control-snapshot.schema.json",
    ):
        schema = _load(path)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(
        _load(schema_path),
        registry=_registry(),
        format_checker=jsonschema.FormatChecker(),
    )


@pytest.mark.parametrize(
    "golden",
    ["snapshot-healthy.json", "snapshot-degraded.json"],
)
def test_snapshot_goldens_validate(golden: str) -> None:
    _validator(_V1 / "mission-control-snapshot.schema.json").validate(
        _load(_V1 / "golden" / golden)
    )


def test_event_goldens_validate() -> None:
    validator = _validator(_V1 / "mission-control-event.schema.json")
    for event in _load(_V1 / "golden" / "events-live.json")["events"]:
        validator.validate(event)


def test_degraded_golden_actually_exercises_partial_failure() -> None:
    """The example that matters most is the mixed one.

    A client that only ever saw a healthy payload will render an unavailable
    lane as an empty one, which is the failure this contract exists to prevent.
    """

    snapshot = _load(_V1 / "golden" / "snapshot-degraded.json")
    assert snapshot["memory"]["state"] == mc.LANE_UNAVAILABLE
    assert snapshot["memory"]["value"] is None
    assert snapshot["activities"]["state"] == mc.LANE_UNAVAILABLE
    # An unavailable lane still ships an empty list — and a detail, without
    # which the screen can say nothing actionable.
    assert snapshot["activities"]["items"] == []
    assert snapshot["activities"]["detail"]
    assert snapshot["devices"]["state"] == mc.LANE_DEGRADED
    assert snapshot["devices"]["truncated"] is True
    # And a lane that did read stays ok, because one dead source must not black
    # out the screen.
    assert snapshot["companions"]["state"] == mc.LANE_OK


def test_schema_enums_match_the_exported_vocabulary() -> None:
    snapshot = _load(_V1 / "mission-control-snapshot.schema.json")
    defs = snapshot["$defs"]

    assert set(defs["laneHealth"]["properties"]["state"]["enum"]) == mc.LANE_STATES

    presence = defs["deviceLane"]["properties"]["items"]["items"]["properties"][
        "presence"
    ]["properties"]
    assert set(presence["state"]["enum"]) == mc.PRESENCE_STATES
    assert set(presence["source"]["enum"]) == mc.PRESENCE_SOURCES

    companion = defs["companionLane"]["properties"]["items"]["items"]["properties"]
    assert (
        set(companion["lifecycle_state"]["enum"]) == mc.COMPANION_LIFECYCLE_STATES
    )
    # No presence field on a companion. Nothing publishes a companion heartbeat,
    # and a field left open for one eventually gets read as though it were fed.
    assert "presence" not in companion
    assert "online" not in companion

    activity = defs["activityLane"]["properties"]["items"]["items"]["properties"]
    assert set(activity["kind"]["enum"]) == mc.ACTIVITY_KINDS
    hop = activity["route"]["items"]["properties"]
    assert set(hop["node_type"]["enum"]) == mc.HOP_NODE_TYPES
    assert set(hop["direction"]["enum"]) == mc.HOP_DIRECTIONS

    device = defs["deviceLane"]["properties"]["items"]["items"]["properties"]
    assert set(device["role_kind"]["enum"]) == mc.ROLE_KINDS

    service = defs["serviceLane"]["properties"]["items"]["items"]["properties"]
    assert set(service["tier"]["enum"]) == mc.SERVICE_TIERS
    # An unprobed service is unknown, not healthy: the bit that says which has
    # to be required, or a producer can leave it out and a client will assume.
    assert "checked" in defs["serviceLane"]["properties"]["items"]["items"][
        "required"
    ]

    assert snapshot["properties"]["contract_version"]["const"] == mc.CONTRACT_VERSION
    assert snapshot["properties"]["coverage"]["const"] == mc.SNAPSHOT_COVERAGE


def test_event_vocabulary_is_the_audit_envelope_s() -> None:
    envelope = _load(_AUDIT)["properties"]
    event = _load(_V1 / "mission-control-event.schema.json")["properties"]

    # Not copies — references. Asserted so a future edit that inlines them
    # (and thereby lets them drift) fails here.
    audit_id = _load(_AUDIT)["$id"]
    assert event["severity"]["$ref"] == f"{audit_id}#/properties/severity"
    assert event["outcome"]["$ref"] == f"{audit_id}#/properties/outcome"
    assert event["privacy"]["$ref"] == f"{audit_id}#/properties/data_classification"

    assert set(envelope["outcome"]["enum"]) == mc.OUTCOMES
    assert set(envelope["severity"]["enum"]) == mc.SEVERITIES
    assert set(envelope["data_classification"]["enum"]) == mc.PRIVACY_CLASSES

    # The cursor is the audit index's own total order, so it is required on
    # every event: a stream a client cannot resume is a stream a phone cannot use.
    assert "ingest_seq" in _load(
        _V1 / "mission-control-event.schema.json"
    )["required"]
    assert mc.CURSOR_FIELD == "ingest_seq"

    # Staged data must never be able to arrive claiming a Host said it.
    assert set(event["origin"]["enum"]) == mc.EVENT_ORIGINS
    assert "mock" not in event["origin"]["enum"]
