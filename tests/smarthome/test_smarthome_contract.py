"""Smart home v1: vocabulary, registry integrity, and panel wire bounds."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from eidolon_sdk.biz.smarthome import (
    DEVICE_TYPES,
    PANEL_SNAPSHOT_MAX_BYTES,
    Area,
    Command,
    CommandResult,
    CommandTemplate,
    Device,
    PanelArea,
    PanelCandidate,
    PanelChange,
    PanelDelta,
    PanelDevice,
    PanelSnapshot,
    Registry,
    Scene,
    SmartHomeError,
    VoiceResult,
    initial_state,
    validate_command,
    validate_state,
)
from eidolon_sdk.biz.smarthome.samples import apartment

ROOT = Path(__file__).resolve().parents[2]


def cmd(trait, command, device_id="d", **params):
    return Command(device_id=device_id, trait=trait, command=command, params=params)


def test_sample_apartment_is_the_laya_evaluation_home():
    registry = apartment()
    assert len(registry.devices) == 18
    assert [s.name for s in registry.scenes] == ["回家", "离家", "观影", "睡眠"]
    assert registry.device("living.ac").type == "climate"


@pytest.mark.parametrize("kind", sorted(DEVICE_TYPES))
def test_every_type_starts_in_a_valid_state(kind):
    validate_state(kind, initial_state(kind))


def test_state_must_carry_exactly_the_trait_keys():
    with pytest.raises(ValueError, match="STATE_KEYS_MISMATCH"):
        validate_state("light", {"on": True})
    with pytest.raises(ValueError, match="STATE_TYPE_MISMATCH"):
        validate_state("light", {"on": True, "level": True})
    with pytest.raises(ValueError, match="STATE_MODE_UNKNOWN"):
        validate_state("climate", initial_state("climate") | {"mode": "turbo"})


@pytest.mark.parametrize(
    "kind, command",
    [
        ("light", cmd("on_off", "on")),
        ("light", cmd("level", "step", delta=-20)),
        ("climate", cmd("thermostat", "set_target", celsius=24)),
        ("climate", cmd("thermostat", "set_mode", mode="heat")),
        ("water_heater", cmd("thermostat", "set_target", celsius=45)),
        ("media", cmd("volume", "mute", muted=True)),
        ("appliance", cmd("operational", "dock")),
    ],
)
def test_valid_commands(kind, command):
    validate_command(kind, command)


@pytest.mark.parametrize(
    "kind, command, code",
    [
        ("light", cmd("thermostat", "set_target", celsius=24), "UNSUPPORTED_COMMAND"),
        ("light", cmd("level", "dim"), "UNSUPPORTED_COMMAND"),
        ("light", cmd("level", "set"), "INVALID_PARAMS"),
        ("light", cmd("level", "set", value=True), "INVALID_PARAMS"),
        ("light", cmd("level", "set", value=50.5), "INVALID_PARAMS"),
        ("light", cmd("level", "set", value=101), "OUT_OF_RANGE"),
        # The same trait takes the device type's bounds, not a global range.
        ("climate", cmd("thermostat", "set_target", celsius=45), "OUT_OF_RANGE"),
        ("water_heater", cmd("thermostat", "set_target", celsius=24), "OUT_OF_RANGE"),
        ("water_heater", cmd("thermostat", "set_mode", mode="cool"), "OUT_OF_RANGE"),
    ],
)
def test_rejected_commands_carry_a_wire_code(kind, command, code):
    with pytest.raises(SmartHomeError) as err:
        validate_command(kind, command)
    assert err.value.code == code


def test_registry_rejects_dangling_references():
    area = Area(area_id="living", name="客厅")
    light = Device(device_id="l", name="灯", type="light", area_id="living")
    with pytest.raises(ValidationError, match="DEVICE_AREA_UNKNOWN"):
        Registry(revision=1, devices=(light,))
    with pytest.raises(ValidationError, match="DUPLICATE_DEVICE"):
        Registry(revision=1, areas=(area,), devices=(light, light))
    with pytest.raises(ValidationError, match="SCENE_DEVICE_UNKNOWN"):
        Registry(revision=1, areas=(area,), scenes=(Scene(scene_id="s", name="回家", actions=(cmd("on_off", "on", "x"),)),))
    with pytest.raises(ValidationError):
        Registry(
            revision=1, areas=(area,), devices=(light,),
            scenes=(Scene(scene_id="s", name="回家", actions=(cmd("thermostat", "set_target", "l", celsius=24),)),),
        )


def test_largest_allowed_snapshot_fits_the_panel_budget():
    # 32 areas, 128 devices and 16 scenes, every name at its 32-character limit,
    # must fit the 64 KiB snapshot budget, or the caps contradict each other.
    areas = tuple(PanelArea(area_id=f"a{i}", name="房" * 32) for i in range(32))
    devices = tuple(
        PanelDevice(device_id=f"device.{i:03d}", name="设" * 32, type="climate", area_id=f"a{i % 32}",
                    state=initial_state("climate") | {"current_c": 27.5})
        for i in range(128)
    )
    snapshot = PanelSnapshot(revision=1, seq=0, areas=areas, devices=devices)
    assert snapshot.devices[-1].device_id == "device.127"


def test_snapshot_and_delta_integrity():
    with pytest.raises(ValidationError, match="PANEL_AREA_UNKNOWN"):
        PanelSnapshot(revision=1, seq=0, panel_area_id="nowhere")
    light = initial_state("light")
    with pytest.raises(ValidationError, match="DUPLICATE_CHANGE"):
        PanelDelta(revision=1, seq=1, source={"kind": "touch"},
                   changes=(PanelChange(device_id="l", state=light), PanelChange(device_id="l", state=light)))
    with pytest.raises(ValidationError):
        PanelDelta(revision=1, seq=0, source={"kind": "touch"}, changes=(PanelChange(device_id="l", state=light),))
    assert PANEL_SNAPSHOT_MAX_BYTES == 65536


def test_voice_result_shapes():
    VoiceResult(turn_id="t", utterance="调一下", outcome="clarification", message="想调节哪个设备？")
    VoiceResult(turn_id="t", utterance="打开空调", outcome="executed", message="已打开客厅空调")
    both = (PanelCandidate(device_id="a", name="客厅空调"), PanelCandidate(device_id="b", name="主卧空调"))
    VoiceResult(turn_id="t", utterance="打开空调", outcome="ambiguous", message="哪台？",
                candidates=both, command=CommandTemplate(trait="on_off", command="on"))
    with pytest.raises(ValidationError, match="CANDIDATES_DO_NOT_MATCH_OUTCOME"):
        VoiceResult(turn_id="t", utterance="打开空调", outcome="ambiguous", message="哪台？",
                    candidates=both[:1], command=CommandTemplate(trait="on_off", command="on"))
    with pytest.raises(ValidationError, match="COMMAND_TEMPLATE"):
        VoiceResult(turn_id="t", utterance="打开空调", outcome="ambiguous", message="哪台？", candidates=both)
    with pytest.raises(ValidationError, match="CANDIDATES_DO_NOT_MATCH_OUTCOME"):
        VoiceResult(turn_id="t", utterance="x", outcome="executed", message="好", candidates=both)


def test_command_result_is_honest():
    with pytest.raises(ValidationError, match="FAILED_RESULT_NEEDS_CODE"):
        CommandResult(device_id="d", status="failed")
    with pytest.raises(ValidationError, match="SUCCEEDED_RESULT_NEEDS_STATE"):
        CommandResult(device_id="d", status="succeeded")
    # Unknown is allowed without a state: nobody knows what the device did.
    CommandResult(device_id="d", status="unknown", code="DEADLINE_EXCEEDED")


def test_golden_vectors_are_current():
    path = ROOT / "contracts/smarthome/v1/generate_goldens.py"
    spec = importlib.util.spec_from_file_location("smarthome_goldens", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, vector in module.vectors().items():
        on_disk = (path.parent / "golden" / name).read_text(encoding="utf-8")
        assert on_disk == module.render(vector), f"{name} is stale; rerun generate_goldens.py"


@pytest.mark.parametrize("package", ["smarthome", "interpretation"])
def test_contract_packages_import_nothing_but_pydantic_and_themselves(package):
    allowed = ("pydantic", "typing", "dataclasses", "json", "__future__", f"eidolon_sdk.biz.{package}")
    for path in (ROOT / "eidolon_sdk/biz" / package).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.startswith(allowed), f"{path.name} imports {name}"


def test_registry_errors_are_typed_and_names_are_unique_per_room():
    from eidolon_sdk.biz.smarthome import RegistryError

    living = Area(area_id="living", name="客厅")
    master = Area(area_id="master", name="主卧")
    lamp = Device(device_id="a", name="吸顶灯", type="light", area_id="living")
    with pytest.raises(ValidationError) as err:
        Registry(revision=1, areas=(living,),
                 devices=(lamp, Device(device_id="b", name="吸顶灯", type="light", area_id="living")))
    cause = err.value.errors()[0]["ctx"]["error"]
    assert isinstance(cause, RegistryError) and cause.code == "DUPLICATE_DEVICE_NAME_IN_AREA"
    assert str(cause) == "DUPLICATE_DEVICE_NAME_IN_AREA"
    # The same name in two rooms is fine; the room tells them apart.
    Registry(revision=1, areas=(living, master),
             devices=(lamp, Device(device_id="b", name="吸顶灯", type="light", area_id="master")))


def test_offline_device_may_have_no_state_but_online_must():
    PanelDevice(device_id="c", name="摄像头", type="camera", online=False)
    with pytest.raises(ValidationError, match="ONLINE_DEVICE_NEEDS_STATE"):
        PanelDevice(device_id="c", name="摄像头", type="camera")


def test_execute_targets_commands_or_one_scene():
    from eidolon_sdk.biz.smarthome import ExecuteRequest, ExecuteResult, PanelExecute, validate_execute_result

    origin = {"kind": "voice"}
    ExecuteRequest(request_id="r", scene_id="scene.movie", origin=origin, deadline_ms=1)
    with pytest.raises(ValidationError, match="EXACTLY_ONE_OF_COMMANDS_OR_SCENE"):
        ExecuteRequest(request_id="r", origin=origin, deadline_ms=1)
    with pytest.raises(ValidationError, match="EXACTLY_ONE_OF_COMMANDS_OR_SCENE"):
        PanelExecute(request_id="r", scene_id="s", commands=(cmd("on_off", "on"),))
    refused = ExecuteResult(request_id="r", error="UNKNOWN_SCENE")
    validate_execute_result((), refused)
    with pytest.raises(ValidationError, match="EXACTLY_ONE_OF_RESULTS_OR_ERROR"):
        ExecuteResult(request_id="r")
    ok = ExecuteResult(request_id="r", results=(CommandResult(device_id="d", status="succeeded", state={"on": True}),))
    validate_execute_result((cmd("on_off", "on"),), ok)
    with pytest.raises(ValueError, match="RESULT_ORDER_MISMATCH"):
        validate_execute_result((cmd("on_off", "on", "other"),), ok)


def test_panel_request_round_trip():
    from eidolon_sdk.biz.smarthome import PanelExecute, PanelRequest, PanelSync, panel_request

    body = panel_request(PanelExecute(request_id="t", scene_id="scene.home"))
    assert body["type"] == "smarthome.execute" and body["schema_v"] == 1
    assert PanelRequest.model_validate(body).message().scene_id == "scene.home"
    sync = PanelRequest.model_validate(panel_request(PanelSync(known_revision=3, known_seq=9))).message()
    assert sync.known_seq == 9


def test_color_temp_is_not_in_v1():
    from eidolon_sdk.biz.smarthome import TRAIT_COMMANDS

    assert "color_temp" not in TRAIT_COMMANDS
