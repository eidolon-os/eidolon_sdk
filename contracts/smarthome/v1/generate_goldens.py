"""Generate smart home panel wire vectors with the production SDK.

Firmware host tests read these byte-for-byte from ../eidolon_sdk, the same way
they read contracts/control/v1/golden. Regenerate after any contract change:

    .venv/bin/python contracts/smarthome/v1/generate_goldens.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from eidolon_sdk.biz.control.protocol import build_command_envelope
from eidolon_sdk.biz.smarthome import (
    CAPABILITY_VERSION,
    OP_DELTA,
    OP_RESULT,
    OP_SNAPSHOT,
    ChangeSource,
    Command,
    CommandTemplate,
    PanelArea,
    PanelCandidate,
    PanelChange,
    PanelDelta,
    PanelDevice,
    PanelExecute,
    PanelScene,
    PanelSnapshot,
    PanelSync,
    VoiceResult,
    initial_state,
    panel_request,
)
from eidolon_sdk.biz.smarthome.samples import apartment

HERE = Path(__file__).resolve().parent
DEVICE_ID = "korvo1-golden"
ISSUED = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)  # 1700000000000 ms


def _envelope(command_id: str, op: str, payload: dict) -> dict:
    return build_command_envelope(
        command_id=command_id,
        device_id=DEVICE_ID,
        payload=payload,
        op=op,
        capability_version=CAPABILITY_VERSION,
        ttl_ms=10_000,
        qos="fire_and_forget",
        src_type="channel",
        src_id="channel_provider",
        created_at=ISSUED,
    )


def snapshot() -> PanelSnapshot:
    registry = apartment()
    overrides = {
        "living.main_light": {"on": True, "level": 60},
        "master.bedside": {"on": True, "level": 30},
        "living.curtain": {"position": 70},
        "living.purifier": {"on": True, "speed": 30},
        "living.speaker": {"on": True, "volume": 35},
        "living.ac": {"current_c": 28},
        "master.ac": {"current_c": 27},
        "bath.water_heater": {"on": True},
        "living.thermo": {"temp_c": 24.5, "humidity": 48},
    }
    devices = []
    for device in registry.devices:
        if device.device_id == "entry.camera":
            # An offline device nobody has reported yet: no state at all.
            devices.append(PanelDevice(device_id=device.device_id, name=device.name, type=device.type,
                                       area_id=device.area_id, online=False))
            continue
        state = initial_state(device.type) | overrides.get(device.device_id, {})
        devices.append(
            PanelDevice(
                device_id=device.device_id, name=device.name, type=device.type,
                area_id=device.area_id, state=state,
            )
        )
    return PanelSnapshot(
        revision=registry.revision,
        seq=0,
        panel_area_id="living",
        utc_offset_minutes=480,
        areas=tuple(PanelArea(area_id=a.area_id, name=a.name) for a in registry.areas),
        devices=tuple(devices),
        scenes=tuple(PanelScene(scene_id=s.scene_id, name=s.name) for s in registry.scenes),
    )


def vectors() -> dict[str, dict]:
    ac = next(d for d in snapshot().devices if d.device_id == "living.ac")
    delta = PanelDelta(
        revision=1,
        seq=1,
        source=ChangeSource(kind="voice", label="面板语音"),
        changes=(PanelChange(device_id="living.ac", state=ac.state | {"on": True}),),
    )
    executed = VoiceResult(
        turn_id="turn-golden-1", utterance="打开空调", outcome="executed", message="已打开客厅空调 · 26°C",
    )
    ambiguous = VoiceResult(
        turn_id="turn-golden-2",
        utterance="打开空调",
        outcome="ambiguous",
        message="要打开哪台空调？",
        candidates=(
            PanelCandidate(device_id="living.ac", name="客厅空调"),
            PanelCandidate(device_id="master.ac", name="主卧空调"),
        ),
        command=CommandTemplate(trait="on_off", command="on"),
    )
    answered = VoiceResult(
        turn_id="turn-golden-3", utterance="客厅空调开着吗", outcome="answered", message="客厅空调开着，制冷 26°C",
    )
    execute = PanelExecute(
        request_id="touch-golden-1",
        commands=(Command(device_id="living.main_light", trait="level", command="set", params={"value": 40}),),
    )
    scene = PanelExecute(request_id="touch-golden-2", scene_id="scene.movie")
    return {
        "panel-snapshot.json": _envelope("snapshot-golden", OP_SNAPSHOT, snapshot().model_dump(mode="json")),
        "panel-delta.json": _envelope("delta-golden", OP_DELTA, delta.model_dump(mode="json")),
        "voice-result-executed.json": _envelope("result-golden-1", OP_RESULT, executed.model_dump(mode="json")),
        "voice-result-ambiguous.json": _envelope("result-golden-2", OP_RESULT, ambiguous.model_dump(mode="json")),
        "voice-result-answered.json": _envelope("result-golden-3", OP_RESULT, answered.model_dump(mode="json")),
        # Upward: the full body a panel publishes on PANEL_REQUEST_TOPIC.
        "panel-execute-request.json": panel_request(execute),
        "panel-scene-request.json": panel_request(scene),
        "panel-sync-request.json": panel_request(PanelSync(known_revision=1, known_seq=0)),
    }


def render(vector: dict) -> str:
    return json.dumps(vector, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    (HERE / "golden").mkdir(exist_ok=True)
    for name, vector in vectors().items():
        (HERE / "golden" / name).write_text(render(vector), encoding="utf-8")
