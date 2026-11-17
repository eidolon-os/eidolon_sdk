import itertools

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.capabilities import installed_presentations, installed_registry
from eidolon_sdk.biz.system_data.models import CompanionRuntimeSnapshot
from eidolon_sdk.biz.tools import (
    CompanionToolPolicy,
    ToolCatalog,
    ToolCatalogEntry,
    ToolPolicy,
    ToolPolicyChange,
    ToolReservation,
    apply_changes,
    blocked_by,
    granted,
)


def entry(key, *, default=True, body=False, reserved=False):
    return ToolCatalogEntry(
        key=key,
        label=key,
        group="general",
        kind="brain",
        side_effect=False,
        body_control=body,
        default_enabled=default,
        reserved=ToolReservation(reason="interactive_session") if reserved else None,
    )


@pytest.mark.parametrize(
    "default, owner_value, companion_value",
    list(itertools.product([True, False], [None, True, False], [None, True, False])),
)
def test_granted_is_both_layers_over_the_default(default, owner_value, companion_value):
    catalog = ToolCatalog.of([entry("t", default=default)])
    owner = ToolPolicy(overrides={} if owner_value is None else {"t": owner_value})
    companion = CompanionToolPolicy(
        overrides={} if companion_value is None else {"t": companion_value}
    )
    on_globally = default if owner_value is None else owner_value
    on_for_companion = default if companion_value is None else companion_value

    assert ("t" in granted(catalog, owner, companion)) == (on_globally and on_for_companion)


def test_reserved_is_never_granted_even_when_switched_on():
    catalog = ToolCatalog.of([entry("t", reserved=True)])
    on = ToolPolicy(overrides={"t": True})

    assert granted(catalog, on, CompanionToolPolicy(overrides={"t": True})) == frozenset()
    assert blocked_by(catalog.tools[0], on, None) == "reserved"


def test_layers_report_the_first_that_blocks():
    body = entry("motion.nod", body=True)
    owner_off = ToolPolicy(overrides={"motion.nod": False})
    no_body = CompanionToolPolicy(allow_body_control=False, overrides={"motion.nod": False})

    assert blocked_by(body, owner_off, no_body) == "global"
    assert blocked_by(body, None, no_body) == "body_control"
    assert blocked_by(body, None, CompanionToolPolicy(overrides={"motion.nod": False})) == "companion"
    assert blocked_by(body, None, None) is None


def test_body_control_gates_only_body_tools_and_keeps_choices():
    catalog = ToolCatalog.of([entry("motion.nod", body=True), entry("get_time")])
    off = CompanionToolPolicy(allow_body_control=False, overrides={"motion.nod": True})

    assert granted(catalog, None, off) == {"get_time"}
    back_on = apply_changes(off, ToolPolicyChange(expected_revision=0, allow_body_control=True))
    assert back_on.overrides == {"motion.nod": True}
    assert granted(catalog, None, back_on) == {"get_time", "motion.nod"}


def test_apply_changes_sets_removes_and_bumps_once():
    policy = ToolPolicy(revision=2, overrides={"get_time": False})

    changed = apply_changes(
        policy, ToolPolicyChange(expected_revision=2, changes={"get_time": None, "get_weather": False})
    )

    assert changed.revision == 3
    assert changed.overrides == {"get_weather": False}
    assert policy.overrides == {"get_time": False}


def test_apply_changes_without_difference_returns_the_same_policy():
    policy = CompanionToolPolicy(revision=4, overrides={"get_time": False})

    same = apply_changes(
        policy,
        ToolPolicyChange(expected_revision=4, changes={"get_time": False, "get_weather": None},
                         allow_body_control=True),
    )

    assert same is policy


def test_owner_policy_has_no_body_control_switch():
    with pytest.raises(ValueError):
        apply_changes(ToolPolicy(), ToolPolicyChange(expected_revision=0, allow_body_control=False))


@pytest.mark.parametrize("raw", [
    {"expected_revision": 0},
    {"expected_revision": 0, "changes": {}},
    {"expected_revision": -1, "changes": {"get_time": False}},
    {"expected_revision": 0, "changes": {"Get Time": False}},
])
def test_change_must_name_valid_keys_and_change_something(raw):
    with pytest.raises(ValidationError):
        ToolPolicyChange.model_validate(raw)


@pytest.mark.parametrize("raw", [
    {"allow": ["get_time"]},
    {"deny": ["get_time"]},
    {"overrides": {"get_time": "no"}},
    {"overrides": {f"t{i}": False for i in range(257)}},
    {"allow_body_control": "false"},
])
def test_companion_policy_refuses_retired_and_invalid_documents(raw):
    with pytest.raises(ValidationError):
        CompanionToolPolicy.model_validate(raw)


def test_catalog_refuses_duplicates_and_digests_its_entries():
    with pytest.raises(ValueError):
        ToolCatalog.of([entry("t"), entry("t")])

    first = ToolCatalog.of([entry("b"), entry("a")])
    assert [tool.key for tool in first.tools] == ["a", "b"]
    assert first.catalog_revision == ToolCatalog.of([entry("a"), entry("b")]).catalog_revision
    assert first.catalog_revision != ToolCatalog.of([entry("a")]).catalog_revision


def test_every_installed_model_tool_has_a_presentation():
    model_tools = {d.name for d in installed_registry().definitions() if d.model_tool}

    assert set(installed_presentations()) == model_tools


def test_runtime_snapshot_reads_the_owner_policy_when_present():
    base = {
        "contract_version": "1",
        "operation": "companion.runtime-snapshot",
        "owner_id": "owner",
        "companion_id": "companion",
        "lifecycle_state": "active",
        "runtime_config": {},
        "memory_realm": {"realm_id": "realm", "lifecycle_state": "active"},
        "persona_genome": {
            "genome_id": "g", "version": 1, "lifecycle_state": "committed",
            "schema_version": "1", "genome_hash": "h", "realizer_version": "1", "genome": {},
        },
    }

    assert CompanionRuntimeSnapshot.model_validate(base).owner_tool_policy is None
    snapshot = CompanionRuntimeSnapshot.model_validate(
        {**base, "owner_tool_policy": {"revision": 1, "overrides": {"get_time": False}}}
    )
    assert snapshot.owner_tool_policy == ToolPolicy(revision=1, overrides={"get_time": False})


def test_device_restriction_is_one_sorted_set_of_valid_keys():
    from eidolon_sdk.biz.tools import DeviceToolRestriction

    restriction = DeviceToolRestriction(revision=1, denied=["vision.look", "get_weather", "vision.look"])

    assert restriction.denied == ("get_weather", "vision.look")
    with pytest.raises(ValidationError):
        DeviceToolRestriction(revision=0, denied=())
    with pytest.raises(ValidationError):
        DeviceToolRestriction(revision=1, denied=("Not A Key",))
    with pytest.raises(ValidationError):
        DeviceToolRestriction(revision=1, denied=tuple(f"t{i}" for i in range(129)))
