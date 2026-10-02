"""Smart home v2: per-device traits, provider accounts, delegated results.

Every new field is optional and defaults to the v1 meaning; the panel wire does
not change, so the v1 goldens must still load byte-for-byte.
"""

from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.smarthome import (
    AccountSchema,
    Command,
    CommandResult,
    Device,
    DiscoveredDevice,
    ExecuteResult,
    Limits,
    Observation,
    PanelDevice,
    PanelSnapshot,
    ProviderAccount,
    Registry,
    Scene,
    SmartHomeError,
    VoiceResult,
    device_spec,
    device_traits,
    provider_binding,
    validate_device_command,
    validate_device_state,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "contracts" / "smarthome" / "v1" / "golden"


def light(**changes):
    return Device(device_id="l", name="灯", type="light", **changes)


def cmd(trait, command, device_id="l", **params):
    return Command(device_id=device_id, trait=trait, command=command, params=params)


def test_v1_device_is_unchanged_and_means_the_type_preset():
    device = light()
    assert device.traits is None and device.source == "manual" and device.overrides == ()
    assert device_traits(device) == ("on_off", "level")
    assert device.model_dump(mode="json")["provider"] == "virtual"


def test_traits_narrow_the_preset_and_cannot_leave_it():
    plain = light(traits=("on_off",))
    validate_device_state(plain, {"on": True})
    with pytest.raises(ValueError, match="STATE_KEYS_MISMATCH"):
        validate_device_state(plain, {"on": True, "level": 50})
    with pytest.raises(SmartHomeError) as refused:
        validate_device_command(plain, cmd("level", "set", value=10))
    assert refused.value.code == "UNSUPPORTED_COMMAND"
    with pytest.raises(ValidationError, match="DEVICE_TRAITS_NOT_IN_TYPE"):
        light(traits=("lock",))
    with pytest.raises(ValidationError, match="DEVICE_TRAITS_NOT_IN_TYPE"):
        light(traits=("on_off", "on_off"))


def test_limits_replace_the_type_bounds():
    ac = Device(
        device_id="ac",
        name="空调",
        type="climate",
        limits=Limits(target_c=(18, 28), modes=("cool", "heat")),
    )
    assert device_spec(ac).target_c == (18, 28)
    validate_device_command(ac, cmd("thermostat", "set_target", device_id="ac", celsius=28))
    with pytest.raises(SmartHomeError) as refused:
        validate_device_command(ac, cmd("thermostat", "set_target", device_id="ac", celsius=30))
    assert refused.value.code == "OUT_OF_RANGE"
    with pytest.raises(SmartHomeError):
        validate_device_command(ac, cmd("thermostat", "set_mode", device_id="ac", mode="dry"))
    with pytest.raises(ValidationError, match="LIMITS_TARGET_C_INVERTED"):
        Limits(target_c=(30, 18))


def test_registry_validates_scene_actions_against_the_device_not_the_type():
    plain = light(traits=("on_off",))
    with pytest.raises(ValidationError):
        Registry(
            revision=1,
            devices=(plain,),
            scenes=(Scene(scene_id="s", name="夜", actions=(cmd("level", "set", value=10),)),),
        )
    Registry(
        revision=1,
        devices=(plain,),
        scenes=(Scene(scene_id="s", name="夜", actions=(cmd("on_off", "on"),)),),
    )


def test_scene_is_actions_or_a_provider_scene_never_both():
    Scene(scene_id="s", name="回家", provider_ref="scene.home", provider="homeassistant:a1")
    with pytest.raises(ValidationError, match="EXACTLY_ONE_OF_ACTIONS_OR_PROVIDER_REF"):
        Scene(scene_id="s", name="回家")
    with pytest.raises(ValidationError, match="EXACTLY_ONE_OF_ACTIONS_OR_PROVIDER_REF"):
        Scene(
            scene_id="s",
            name="回家",
            actions=(cmd("on_off", "on"),),
            provider_ref="x",
            provider="k:a",
        )
    with pytest.raises(ValidationError, match="PROVIDER_SCENE_NEEDS_PROVIDER"):
        Scene(scene_id="s", name="回家", provider_ref="scene.home")


def test_provider_binding_splits_kind_and_account():
    assert provider_binding("virtual") == ("virtual", "")
    assert provider_binding("homeassistant:acc_01") == ("homeassistant", "acc_01")
    assert provider_binding("k:a:b") == ("k", "a:b")


def test_delegated_result_carries_the_platform_answer_and_no_state():
    CommandResult(device_id="l", status="delegated", platform_answer="好的，为您打开客厅主灯")
    with pytest.raises(ValidationError, match="DELEGATED_RESULT_NEEDS_PLATFORM_ANSWER"):
        CommandResult(device_id="l", status="delegated")
    with pytest.raises(ValidationError, match="DELEGATED_RESULT_HAS_NO_STATE"):
        CommandResult(device_id="l", status="delegated", platform_answer="ok", state={"on": True})
    with pytest.raises(ValidationError, match="PLATFORM_ANSWER_ONLY_WHEN_DELEGATED"):
        CommandResult(device_id="l", status="succeeded", state={"on": True}, platform_answer="ok")
    CommandResult(device_id="l", status="failed", code="PLATFORM_REJECTED")
    ExecuteResult(
        request_id="r",
        results=(CommandResult(device_id="l", status="delegated", platform_answer="ok"),),
    )


def test_panel_device_state_may_be_a_subset_of_the_type_keys():
    PanelDevice(device_id="l", name="灯", type="light", state={"on": True})
    with pytest.raises(ValidationError, match="STATE_KEYS_UNKNOWN"):
        PanelDevice(device_id="l", name="灯", type="light", state={"on": True, "locked": False})
    with pytest.raises(ValidationError, match="STATE_TYPE_MISMATCH"):
        PanelDevice(device_id="l", name="灯", type="light", state={"on": 1})


def test_account_and_discovery_contracts():
    schema = AccountSchema(
        kind="homeassistant",
        label="Home Assistant",
        fields=(
            {"name": "url", "label": "地址", "kind": "url"},
            {"name": "token", "label": "长效访问令牌", "kind": "secret"},
        ),
    )
    assert [f.name for f in schema.fields] == ["url", "token"]
    account = ProviderAccount(
        account_id="acc_01",
        kind="homeassistant",
        label="家",
        status="pending",
        choices=({"value": "h1", "label": "我的家"},),
    )
    assert account.model_dump(mode="json")["status"] == "pending"
    found = DiscoveredDevice(
        external_ref="light.living",
        name="客厅主灯",
        suggested_type="light",
        traits=("on_off",),
        area_name="客厅",
    )
    assert found.reachable is True
    Observation(device_id="l", reachable=False, observed_at_ms=1, seq=3)
    with pytest.raises(ValidationError):
        AccountSchema(kind="Home-Assistant", label="x")


def test_v1_goldens_still_load_unchanged():
    snapshot = json.loads((GOLDEN / "panel-snapshot.json").read_text(encoding="utf-8"))["payload"]
    assert PanelSnapshot.model_validate(snapshot).model_dump(mode="json") == snapshot
    voice = json.loads((GOLDEN / "voice-result-executed.json").read_text(encoding="utf-8"))[
        "payload"
    ]
    assert VoiceResult.model_validate(voice).model_dump(mode="json") == voice


def test_contract_names_no_ecosystem():
    """X2: ecosystem vocabulary stays inside Provider adapters, never in the contract."""
    source = (ROOT / "eidolon_sdk" / "biz" / "smarthome" / "__init__.py").read_text(
        encoding="utf-8"
    )
    # Identifiers and short string literals are the contract; comments and
    # docstrings may name ecosystems when explaining a decision.
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    code = " ".join(
        t.string
        for t in tokens
        if t.type == tokenize.NAME or (t.type == tokenize.STRING and len(t.string) < 80)
    )
    forbidden = re.compile(
        r"entity_id|hvac|cluster|homeId|resourceId|home_assistant|xiaomi|tuya|\bmatter\b", re.I
    )
    assert forbidden.search(code) is None, forbidden.search(code)
