"""The Mission Control contract, held to its own schemas.

Lives under ``contracts/mission_control`` rather than ``contracts/local_api``:
the payload is a management-plane projection, and naming a directory after
``/api/local/v1`` — the Owner product surface the convergence plan deletes —
would have it lie in whichever direction the reader was going. It folds into
``eidolon_admin/contracts/management/v1``'s generated OpenAPI document when that
describes these routes; until then this is the working description.

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
_V1 = _ROOT / "contracts/mission_control/v1"
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
    assert snapshot["services"]["state"] == mc.LANE_OK


def test_the_snapshot_carries_no_identity() -> None:
    """This projection observes; it does not say who exists.

    Three versions of this schema got the ownership wrong in three ways: a
    per-row ``is_primary`` flag (a second adjudication of a question the roster
    already answers), then a snapshot-level ``default_companion_id``, then a
    companions lane. All three were identity, and identity has authorities — the
    roster for which Companions exist and ``/context`` for the Owner and the
    default pointer, whose fields are authority fields rather than projections.

    The route takes ``?companion_id=``, which is the tell: a caller that has to
    name the Companion already knows which ones there are.
    """

    snapshot = _load(_V1 / "mission-control-snapshot.schema.json")
    for absent in ("owner", "companions", "default_companion_id"):
        assert absent not in snapshot["properties"], absent
        assert absent not in snapshot["required"]
    for absent in ("ownerLane", "companionLane"):
        assert absent not in snapshot["$defs"], absent

    # Every remaining lane is something observed, keyed by an id the caller holds.
    observed = {
        "devices",
        "activities",
        "turns",
        "jobs",
        "memory",
        "services",
        "events",
    }
    lanes = set(snapshot["properties"]) - {
        "contract_version",
        "coverage",
        "generated_at",
        "cursor",
    }
    assert lanes == observed

    for name in ("snapshot-healthy.json", "snapshot-degraded.json"):
        golden = _load(_V1 / "golden" / name)
        for absent in ("owner", "companions", "default_companion_id"):
            assert absent not in golden, f"{name}: {absent}"


def test_schema_enums_match_the_exported_vocabulary() -> None:
    snapshot = _load(_V1 / "mission-control-snapshot.schema.json")
    defs = snapshot["$defs"]

    assert set(defs["laneHealth"]["properties"]["state"]["enum"]) == mc.LANE_STATES

    presence = defs["deviceLane"]["properties"]["items"]["items"]["properties"][
        "presence"
    ]["properties"]
    assert set(presence["state"]["enum"]) == mc.PRESENCE_STATES
    assert set(presence["source"]["enum"]) == mc.PRESENCE_SOURCES

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

    memory = defs["memoryLane"]["properties"]["value"]["properties"]
    assert "runners_online" not in memory
    assert "runners_total" not in memory
    assert set(memory["materialization_state"]["enum"]) == {
        "ready",
        "materializing",
        "degraded",
        "unavailable",
    }


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


def test_the_companion_lifecycle_is_not_this_contracts_to_invent() -> None:
    """It was never this contract's vocabulary, and now it is not its field.

    Two mistakes ended the same way. This schema had invented
    active/pending/suspended/removed while the Companion authority publishes
    active/retiring/archived/deleting — an archived Companion had no
    representable value, and both goldens asserted a ``pending`` no Host can
    send. The fix then was to import the shared vocabulary. The fix now is that
    the field is gone: lifecycle is identity, identity belongs to the roster, and
    this projection carries only what it observed.

    The shared module still has to agree with the authority, because other
    consumers read it, so that stays asserted here.
    """

    from eidolon_sdk.biz.contracts import companion, mission_control as mc

    assert mc.COMPANION_LIFECYCLE_STATES == frozenset(
        companion.COMPANION_LIFECYCLE_STATES
    )

    schema = json.dumps(_load(_V1 / "mission-control-snapshot.schema.json"))
    assert "lifecycle_state" not in schema
    assert "companionLane" not in schema
