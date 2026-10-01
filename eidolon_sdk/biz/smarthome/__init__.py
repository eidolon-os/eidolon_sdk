"""Smart home v1: the Owner's home as data, commands against it, and panel wire.

Three kinds of fact, each with one writer:

- The registry (areas, devices, scenes, where Eidolon devices are placed) is
  Owner master data. Mobile edits it through the management API; System Data
  stores it. Nothing else writes it.
- A device's current state belongs to the Provider that implements it (the
  host's virtual provider first; Home Assistant or a Matter bridge later).
- A panel (korvo-1) holds neither. It renders snapshots and deltas it is sent
  and submits touch commands; its copy is a cache that may be stale.

This module is wire contract only: validation and vocabulary, never storage,
transport, or the semantics of executing a command.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1
CAPABILITY_VERSION = 1

# The property a panel's manifest pins, and the control ops it accepts.
PANEL_PROFILE_PROPERTY = "smarthome.profile"
PANEL_PROFILE = "smarthome.panel.v1"
OP_SNAPSHOT = "smarthome.snapshot"
OP_DELTA = "smarthome.delta"
OP_RESULT = "smarthome.result"
# What a panel sends up, on its own channel and its own topic. These are
# requests, not device events: biz.events carries facts for observers, while a
# touch asks the host to act. The Provider admits them only from the panel the
# channel was minted for, as it does for session_control requests.
PANEL_REQUEST_TOPIC = "eidolon.smarthome"
REQUEST_EXECUTE = "smarthome.execute"
REQUEST_SYNC = "smarthome.sync"

# Scenes are not a device trait. An interpretation names one as a candidate of
# kind SCENE_KIND and proposes Action(trait=SCENE_TRAIT, command=SCENE_COMMAND);
# execution carries the scene_id and the Runtime expands it, in one place.
SCENE_KIND = "scene"
SCENE_TRAIT = "scene"
SCENE_COMMAND = "activate"

# Snapshots and deltas are sent by the Channel Provider, whose control payloads
# the firmware accepts up to 160 KiB; a voice result comes from the session's
# agent, which is capped at 4096 bytes. Stay well inside both.
PANEL_SNAPSHOT_MAX_BYTES = 64 * 1024
VOICE_RESULT_MAX_BYTES = 3072

MAX_AREAS = 32
MAX_DEVICES = 128
MAX_SCENES = 16
MAX_PLACEMENTS = 64
MAX_COMMANDS = 32
MAX_PANEL_COMMANDS = 8
MAX_DELTA_CHANGES = 32
MAX_SCENE_ACTIONS = 32

# Error codes a Provider or Runtime returns per command.
ERROR_UNKNOWN_DEVICE = "UNKNOWN_DEVICE"
ERROR_UNSUPPORTED_COMMAND = "UNSUPPORTED_COMMAND"
ERROR_INVALID_PARAMS = "INVALID_PARAMS"
ERROR_OUT_OF_RANGE = "OUT_OF_RANGE"
ERROR_DEVICE_OFFLINE = "DEVICE_OFFLINE"
ERROR_DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
ERROR_UNKNOWN_SCENE = "UNKNOWN_SCENE"
ERROR_CODES = frozenset(
    {
        ERROR_UNKNOWN_DEVICE,
        ERROR_UNKNOWN_SCENE,
        ERROR_UNSUPPORTED_COMMAND,
        ERROR_INVALID_PARAMS,
        ERROR_OUT_OF_RANGE,
        ERROR_DEVICE_OFFLINE,
        ERROR_DEADLINE_EXCEEDED,
    }
)

# Codes a registry write is refused with. LIMIT_EXCEEDED is for callers that
# map pydantic's length errors on the MAX_* caps; the validators raise the rest.
REGISTRY_DUPLICATE_AREA = "DUPLICATE_AREA"
REGISTRY_DUPLICATE_AREA_NAME = "DUPLICATE_AREA_NAME"
REGISTRY_DUPLICATE_DEVICE = "DUPLICATE_DEVICE"
REGISTRY_DUPLICATE_DEVICE_NAME = "DUPLICATE_DEVICE_NAME_IN_AREA"
REGISTRY_DUPLICATE_SCENE = "DUPLICATE_SCENE"
REGISTRY_DUPLICATE_PLACEMENT = "DUPLICATE_PLACEMENT"
REGISTRY_DEVICE_AREA_UNKNOWN = "DEVICE_AREA_UNKNOWN"
REGISTRY_PLACEMENT_AREA_UNKNOWN = "PLACEMENT_AREA_UNKNOWN"
REGISTRY_SCENE_DEVICE_UNKNOWN = "SCENE_DEVICE_UNKNOWN"
REGISTRY_LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
REGISTRY_ERROR_CODES = frozenset(
    {
        REGISTRY_DUPLICATE_AREA,
        REGISTRY_DUPLICATE_AREA_NAME,
        REGISTRY_DUPLICATE_DEVICE,
        REGISTRY_DUPLICATE_DEVICE_NAME,
        REGISTRY_DUPLICATE_SCENE,
        REGISTRY_DUPLICATE_PLACEMENT,
        REGISTRY_DEVICE_AREA_UNKNOWN,
        REGISTRY_PLACEMENT_AREA_UNKNOWN,
        REGISTRY_SCENE_DEVICE_UNKNOWN,
        REGISTRY_LIMIT_EXCEEDED,
    }
)

Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
Name = Annotated[str, Field(strict=True, min_length=1, max_length=32, pattern=r"\S")]
Revision = Annotated[int, Field(strict=True, ge=0)]
StateValue = bool | int | float | str | None


class HomeSessionScope(BaseModel):
    """Trusted ingress identity for an independent smart-home Agent session.

    Companion selects who handles the interaction; Owner remains the authority
    for device control. This scope carries no persona prompt or memory content.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    owner_id: Identifier
    companion_id: Identifier
    device_ref: Identifier
    session_id: Identifier


class HomeCommandRequest(HomeSessionScope):
    turn_id: Identifier
    utterance: str = Field(min_length=1, max_length=512)

Trait = Literal[
    "on_off",
    "level",
    "thermostat",
    "fan_speed",
    "position",
    "lock",
    "operational",
    "volume",
    "measure",
]
DeviceType = Literal[
    "light",
    "switch",
    "climate",
    "water_heater",
    "cover",
    "fan",
    "media",
    "appliance",
    "lock",
    "camera",
    "sensor",
]
OriginKind = Literal["voice", "text", "touch", "scene", "mobile", "automation"]


class RegistryError(ValueError):
    """A registry the validators refuse. ``str(error)`` is the code itself.

    Pydantic wraps it in a ValidationError; the original is at
    ``exc.errors()[0]["ctx"]["error"]``, so callers read ``.code`` rather than
    parsing messages.
    """

    def __init__(self, code: str) -> None:
        if code not in REGISTRY_ERROR_CODES:
            raise ValueError(f"unknown registry error code {code!r}")
        super().__init__(code)
        self.code = code


class SmartHomeError(ValueError):
    """A command or state that the vocabulary rejects, with a wire code."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown smart home error code {code!r}")
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# --- Vocabulary -------------------------------------------------------------

# A parameter is (kind, low, high). Bounds of None come from the device type.
_Param = tuple[str, float | None, float | None]
_PCT: _Param = ("int", 0, 100)
_STEP: _Param = ("int", -100, 100)
_BOOL: _Param = ("bool", None, None)
_MODE: _Param = ("mode", None, None)

TRAIT_COMMANDS: dict[str, dict[str, dict[str, _Param]]] = {
    "on_off": {"on": {}, "off": {}, "toggle": {}},
    "level": {"set": {"value": _PCT}, "step": {"delta": _STEP}},
    "thermostat": {
        "set_mode": {"mode": _MODE},
        "set_target": {"celsius": ("number", None, None)},
        "step": {"delta": ("number", -10, 10)},
    },
    "fan_speed": {"set": {"value": _PCT}},
    "position": {"open": {}, "close": {}, "stop": {}, "set": {"value": _PCT}},
    "lock": {"lock": {}, "unlock": {}},
    "operational": {"start": {}, "pause": {}, "stop": {}, "dock": {}},
    "volume": {"set": {"value": _PCT}, "step": {"delta": _STEP}, "mute": {"muted": _BOOL}},
    "measure": {},
}

# State keys each trait contributes, with the Python types a value may take.
TRAIT_STATE: dict[str, dict[str, tuple[type, ...]]] = {
    "on_off": {"on": (bool,)},
    "level": {"level": (int,)},
    "thermostat": {"mode": (str,), "target_c": (int, float), "current_c": (int, float, type(None))},
    "fan_speed": {"speed": (int,)},
    "position": {"position": (int,)},
    "lock": {"locked": (bool,)},
    "operational": {"run_state": (str,)},
    "volume": {"volume": (int,), "muted": (bool,)},
    "measure": {"temp_c": (int, float, type(None)), "humidity": (int, type(None))},
}

RUN_STATES = ("idle", "running", "paused", "docked")


@dataclass(frozen=True)
class DeviceTypeSpec:
    traits: tuple[str, ...]
    label: str
    target_c: tuple[float, float] | None = None
    modes: tuple[str, ...] = ()
    initial: tuple[tuple[str, StateValue], ...] = ()


DEVICE_TYPES: dict[str, DeviceTypeSpec] = {
    "light": DeviceTypeSpec(("on_off", "level"), "灯", initial=(("on", False), ("level", 60))),
    "switch": DeviceTypeSpec(("on_off",), "开关", initial=(("on", False),)),
    "climate": DeviceTypeSpec(
        ("on_off", "thermostat"),
        "空调",
        target_c=(16, 30),
        modes=("cool", "heat", "auto", "fan", "dry"),
        initial=(("on", False), ("mode", "cool"), ("target_c", 26), ("current_c", None)),
    ),
    "water_heater": DeviceTypeSpec(
        ("on_off", "thermostat"),
        "热水器",
        target_c=(35, 60),
        modes=("heat",),
        initial=(("on", False), ("mode", "heat"), ("target_c", 42), ("current_c", None)),
    ),
    "cover": DeviceTypeSpec(("position",), "窗帘", initial=(("position", 0),)),
    "fan": DeviceTypeSpec(("on_off", "fan_speed"), "风扇/净化/加湿", initial=(("on", False), ("speed", 30))),
    "media": DeviceTypeSpec(("on_off", "volume"), "影音", initial=(("on", False), ("volume", 20), ("muted", False))),
    "appliance": DeviceTypeSpec(("operational",), "家电", initial=(("run_state", "idle"),)),
    "lock": DeviceTypeSpec(("lock",), "门锁", initial=(("locked", True),)),
    "camera": DeviceTypeSpec(("on_off",), "摄像头", initial=(("on", True),)),
    "sensor": DeviceTypeSpec(("measure",), "传感器", initial=(("temp_c", None), ("humidity", None))),
}


def device_type(kind: str) -> DeviceTypeSpec:
    try:
        return DEVICE_TYPES[kind]
    except KeyError:
        raise SmartHomeError(ERROR_UNSUPPORTED_COMMAND, f"unknown device type {kind!r}") from None


def initial_state(kind: str) -> dict[str, StateValue]:
    """The state a newly added virtual device starts in."""
    return dict(device_type(kind).initial)


def validate_state(kind: str, state: dict[str, Any]) -> None:
    """A full state must carry exactly the keys its type's traits define."""
    spec = device_type(kind)
    allowed: dict[str, tuple[type, ...]] = {}
    for trait in spec.traits:
        allowed.update(TRAIT_STATE[trait])
    if set(state) != set(allowed):
        raise ValueError(f"STATE_KEYS_MISMATCH: {sorted(state)} != {sorted(allowed)}")
    for key, value in state.items():
        types = allowed[key]
        # bool is an int subclass; never let True stand in for a number.
        if isinstance(value, bool) and bool not in types:
            raise ValueError(f"STATE_TYPE_MISMATCH: {key}")
        if not isinstance(value, types):
            raise ValueError(f"STATE_TYPE_MISMATCH: {key}")
    if "mode" in state and state["mode"] not in spec.modes:
        raise ValueError("STATE_MODE_UNKNOWN")
    if "run_state" in state and state["run_state"] not in RUN_STATES:
        raise ValueError("STATE_RUN_STATE_UNKNOWN")


# --- Registry (Owner master data) ----------------------------------------------


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Command(Contract):
    device_id: Identifier
    trait: Trait
    command: Identifier
    params: dict[str, bool | int | float | str] = Field(default_factory=dict)


def validate_command(kind: str, command: Command) -> None:
    """Reject a command this device type cannot take. Execution is not decided here."""
    spec = device_type(kind)
    if command.trait not in spec.traits:
        raise SmartHomeError(ERROR_UNSUPPORTED_COMMAND, f"{kind} has no {command.trait}")
    params = TRAIT_COMMANDS[command.trait].get(command.command)
    if params is None:
        raise SmartHomeError(ERROR_UNSUPPORTED_COMMAND, f"{command.trait}.{command.command}")
    if set(command.params) != set(params):
        raise SmartHomeError(ERROR_INVALID_PARAMS, f"expected {sorted(params)}")
    for name, (pkind, low, high) in params.items():
        value = command.params[name]
        if pkind == "bool":
            if not isinstance(value, bool):
                raise SmartHomeError(ERROR_INVALID_PARAMS, name)
            continue
        if pkind == "mode":
            if value not in spec.modes:
                raise SmartHomeError(ERROR_OUT_OF_RANGE, f"mode {value!r}")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SmartHomeError(ERROR_INVALID_PARAMS, name)
        if pkind == "int" and not isinstance(value, int):
            raise SmartHomeError(ERROR_INVALID_PARAMS, name)
        if name == "celsius" and spec.target_c is not None:
            low, high = spec.target_c
        if (low is not None and value < low) or (high is not None and value > high):
            raise SmartHomeError(ERROR_OUT_OF_RANGE, f"{name}={value}")


class Area(Contract):
    area_id: Identifier
    name: Name
    order: Annotated[int, Field(strict=True, ge=0, le=1000)] = 0


class Device(Contract):
    device_id: Identifier
    name: Name
    aliases: Annotated[tuple[Name, ...], Field(max_length=8)] = ()
    type: DeviceType
    area_id: Identifier | None = None
    provider: Identifier = "virtual"
    provider_ref: Identifier | None = None


class Scene(Contract):
    scene_id: Identifier
    name: Name
    actions: Annotated[tuple[Command, ...], Field(min_length=1, max_length=MAX_SCENE_ACTIONS)]


class Placement(Contract):
    """Which area an Eidolon device (a panel, a BOX-3) stands in.

    ``device_ref`` is the Hub device instance id (``DeviceRef.device_instance_id``),
    the same string the Channel Provider binds a channel to.
    """

    device_ref: Identifier
    area_id: Identifier


class Registry(Contract):
    schema_version: Literal[1] = SCHEMA_VERSION
    revision: Revision
    areas: Annotated[tuple[Area, ...], Field(max_length=MAX_AREAS)] = ()
    devices: Annotated[tuple[Device, ...], Field(max_length=MAX_DEVICES)] = ()
    scenes: Annotated[tuple[Scene, ...], Field(max_length=MAX_SCENES)] = ()
    placements: Annotated[tuple[Placement, ...], Field(max_length=MAX_PLACEMENTS)] = ()

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        area_ids = _unique([a.area_id for a in self.areas], REGISTRY_DUPLICATE_AREA)
        device_ids = _unique([d.device_id for d in self.devices], REGISTRY_DUPLICATE_DEVICE)
        _unique([a.name for a in self.areas], REGISTRY_DUPLICATE_AREA_NAME)
        # Two rooms may each have a 吸顶灯; one room may not, or no one can say which.
        _unique([f"{d.area_id}\x00{d.name}" for d in self.devices], REGISTRY_DUPLICATE_DEVICE_NAME)
        _unique([s.scene_id for s in self.scenes], REGISTRY_DUPLICATE_SCENE)
        _unique([p.device_ref for p in self.placements], REGISTRY_DUPLICATE_PLACEMENT)
        for device in self.devices:
            if device.area_id is not None and device.area_id not in area_ids:
                raise RegistryError(REGISTRY_DEVICE_AREA_UNKNOWN)
        for placement in self.placements:
            if placement.area_id not in area_ids:
                raise RegistryError(REGISTRY_PLACEMENT_AREA_UNKNOWN)
        kinds = {d.device_id: d.type for d in self.devices}
        for scene in self.scenes:
            for action in scene.actions:
                if action.device_id not in device_ids:
                    raise RegistryError(REGISTRY_SCENE_DEVICE_UNKNOWN)
                validate_command(kinds[action.device_id], action)
        return self

    def device(self, device_id: str) -> Device | None:
        return next((d for d in self.devices if d.device_id == device_id), None)

    def area_of(self, device_ref: str) -> str | None:
        return next((p.area_id for p in self.placements if p.device_ref == device_ref), None)

    def scene(self, scene_id: str) -> Scene | None:
        return next((s for s in self.scenes if s.scene_id == scene_id), None)


def _unique(values: list[str], code: str) -> set[str]:
    seen = set(values)
    if len(seen) != len(values):
        if code in REGISTRY_ERROR_CODES:
            raise RegistryError(code)
        raise ValueError(code)
    return seen


# --- Execution --------------------------------------------------------------


class Origin(Contract):
    kind: OriginKind
    device_ref: Identifier | None = None
    turn_id: Identifier | None = None
    label: Annotated[str | None, Field(max_length=32)] = None


class ExecuteRequest(Contract):
    """Either explicit commands or one scene, never both.

    Idempotent by request_id within one Owner: a repeat with the same content
    returns the first result without executing again; the same request_id with
    different content is refused as a conflict. "Content" is ``commands`` and
    ``scene_id`` only: a retry recomputes ``deadline_ms`` and may restamp
    ``origin``, and neither makes it a different request. A conflict is a
    caller bug, reported by the transport (HTTP 409), never as an ExecuteResult.
    ``deadline_ms`` is an absolute Unix epoch time in milliseconds; past it
    nothing executes.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    request_id: Identifier
    commands: Annotated[tuple[Command, ...], Field(max_length=MAX_COMMANDS)] = ()
    scene_id: Identifier | None = None
    origin: Origin
    deadline_ms: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if bool(self.commands) == (self.scene_id is not None):
            raise ValueError("EXACTLY_ONE_OF_COMMANDS_OR_SCENE")
        return self


class CommandResult(Contract):
    device_id: Identifier
    status: Literal["succeeded", "failed", "unknown"]
    code: str | None = None
    state: dict[str, StateValue] | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "failed" and self.code not in ERROR_CODES:
            raise ValueError("FAILED_RESULT_NEEDS_CODE")
        if self.status == "succeeded" and self.state is None:
            raise ValueError("SUCCEEDED_RESULT_NEEDS_STATE")
        return self


class ExecuteResult(Contract):
    """One result per executed command, in order, or a refusal of the whole request.

    For explicit commands the order is the request's; for a scene it is the
    scene's actions as stored at execution time. ``error`` refuses the request
    before anything runs (``UNKNOWN_SCENE``, ``DEADLINE_EXCEEDED``) and then
    ``results`` is empty.

    Per command: ``unknown`` only when a command was attempted and no outcome
    came back (a Provider timeout). A command never attempted because the
    deadline passed partway through the request is ``failed`` with
    ``DEADLINE_EXCEEDED``: that outcome is known.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    request_id: Identifier
    results: Annotated[tuple[CommandResult, ...], Field(max_length=MAX_COMMANDS)] = ()
    error: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.error is not None and self.error not in ERROR_CODES:
            raise ValueError("UNKNOWN_ERROR_CODE")
        if (self.error is None) == (not self.results):
            raise ValueError("EXACTLY_ONE_OF_RESULTS_OR_ERROR")
        return self


def validate_execute_result(commands: tuple[Command, ...], result: ExecuteResult) -> None:
    """Check a result lines up with the commands that were executed."""
    if result.error is not None:
        return
    if len(result.results) != len(commands):
        raise ValueError("RESULT_COUNT_MISMATCH")
    for command, item in zip(commands, result.results, strict=True):
        if command.device_id != item.device_id:
            raise ValueError("RESULT_ORDER_MISMATCH")


# --- Panel wire (host <-> korvo-1) -------------------------------------------


class PanelArea(Contract):
    area_id: Identifier
    name: Name


class PanelDevice(Contract):
    device_id: Identifier
    name: Name
    type: DeviceType
    area_id: Identifier | None = None
    online: bool = True
    # Last known state; absent only for an offline device nobody has reported.
    state: dict[str, StateValue] | None = None

    @model_validator(mode="after")
    def validate_device_state(self) -> Self:
        if self.state is None:
            if self.online:
                raise ValueError("ONLINE_DEVICE_NEEDS_STATE")
            return self
        validate_state(self.type, self.state)
        return self


class PanelScene(Contract):
    scene_id: Identifier
    name: Name


class PanelSnapshot(Contract):
    """Everything a panel shows. Sent on connect, on sync, and on any registry change."""

    schema_version: Literal[1] = SCHEMA_VERSION
    revision: Revision
    seq: Revision
    home_name: Name = "我的家"
    panel_area_id: Identifier | None = None
    # The home's offset from UTC, so a panel can show local time. Firmware has
    # no timezone database; its wall clock comes from the Hub's Date header.
    utc_offset_minutes: Annotated[int, Field(strict=True, ge=-720, le=840)] = 0
    areas: Annotated[tuple[PanelArea, ...], Field(max_length=MAX_AREAS)] = ()
    devices: Annotated[tuple[PanelDevice, ...], Field(max_length=MAX_DEVICES)] = ()
    scenes: Annotated[tuple[PanelScene, ...], Field(max_length=MAX_SCENES)] = ()

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        area_ids = _unique([a.area_id for a in self.areas], "DUPLICATE_AREA")
        _unique([d.device_id for d in self.devices], "DUPLICATE_DEVICE")
        _unique([s.scene_id for s in self.scenes], "DUPLICATE_SCENE")
        if self.panel_area_id is not None and self.panel_area_id not in area_ids:
            raise ValueError("PANEL_AREA_UNKNOWN")
        for device in self.devices:
            if device.area_id is not None and device.area_id not in area_ids:
                raise ValueError("DEVICE_AREA_UNKNOWN")
        if _encoded_size(self) > PANEL_SNAPSHOT_MAX_BYTES:
            raise ValueError("SNAPSHOT_TOO_LARGE")
        return self


class PanelChange(Contract):
    device_id: Identifier
    online: bool = True
    # The device's full state after the change, so applying a delta is idempotent.
    state: dict[str, StateValue]


class ChangeSource(Contract):
    kind: OriginKind
    label: Annotated[str | None, Field(max_length=32)] = None


class PanelDelta(Contract):
    """State changes only. A registry change is always a new snapshot, never a delta.

    A panel holding (revision, seq) applies a delta when its revision matches and
    its seq is exactly one past the last; ignores it as a repeat when its seq is
    at or below the last; and sends smarthome.sync on a revision mismatch or a gap.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    revision: Revision
    seq: Annotated[int, Field(strict=True, ge=1)]
    source: ChangeSource
    changes: Annotated[tuple[PanelChange, ...], Field(min_length=1, max_length=MAX_DELTA_CHANGES)]

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        _unique([c.device_id for c in self.changes], "DUPLICATE_CHANGE")
        return self


class PanelCandidate(Contract):
    device_id: Identifier
    name: Name


class CommandTemplate(Contract):
    """The command to run on whichever candidate the person taps."""

    trait: Trait
    command: Identifier
    params: dict[str, bool | int | float | str] = Field(default_factory=dict)


VoiceOutcome = Literal[
    "executed", "partial", "answered", "ambiguous", "clarification", "not_found", "unrelated", "failed", "unavailable"
]


class VoiceResult(Contract):
    """What one spoken command came to, for the panel's result card."""

    schema_version: Literal[1] = SCHEMA_VERSION
    turn_id: Identifier
    utterance: Annotated[str, Field(strict=True, max_length=200)]
    outcome: VoiceOutcome
    message: Annotated[str, Field(strict=True, min_length=1, max_length=120)]
    candidates: Annotated[tuple[PanelCandidate, ...], Field(max_length=8)] = ()
    command: CommandTemplate | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        ambiguous = self.outcome == "ambiguous"
        if ambiguous != (len(self.candidates) >= 2):
            raise ValueError("CANDIDATES_DO_NOT_MATCH_OUTCOME")
        if ambiguous != (self.command is not None):
            raise ValueError("COMMAND_TEMPLATE_DO_NOT_MATCH_OUTCOME")
        _unique([c.device_id for c in self.candidates], "DUPLICATE_CANDIDATE")
        if _encoded_size(self) > VOICE_RESULT_MAX_BYTES:
            raise ValueError("VOICE_RESULT_TOO_LARGE")
        return self


class PanelExecute(Contract):
    """A touch on a tile or a scene button. The host stamps origin from the channel binding."""

    schema_version: Literal[1] = SCHEMA_VERSION
    request_id: Identifier
    commands: Annotated[tuple[Command, ...], Field(max_length=MAX_PANEL_COMMANDS)] = ()
    scene_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if bool(self.commands) == (self.scene_id is not None):
            raise ValueError("EXACTLY_ONE_OF_COMMANDS_OR_SCENE")
        return self


class PanelSync(Contract):
    schema_version: Literal[1] = SCHEMA_VERSION
    known_revision: Revision | None = None
    known_seq: Revision | None = None


class PanelRequest(Contract):
    """The body a panel publishes on PANEL_REQUEST_TOPIC."""

    schema_v: Literal[1] = SCHEMA_VERSION
    type: Literal["smarthome.execute", "smarthome.sync"]
    payload: dict[str, Any]

    def message(self) -> PanelExecute | PanelSync:
        model = PanelExecute if self.type == REQUEST_EXECUTE else PanelSync
        return model.model_validate(self.payload)


def panel_request(message: PanelExecute | PanelSync) -> dict[str, Any]:
    kind = REQUEST_EXECUTE if isinstance(message, PanelExecute) else REQUEST_SYNC
    return PanelRequest(type=kind, payload=message.model_dump(mode="json")).model_dump(mode="json")


def _encoded_size(model: BaseModel) -> int:
    return len(json.dumps(model.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")).encode())


__all__ = [
    "Area",
    "CAPABILITY_VERSION",
    "ChangeSource",
    "Command",
    "CommandResult",
    "CommandTemplate",
    "DEVICE_TYPES",
    "Device",
    "DeviceTypeSpec",
    "ERROR_CODES",
    "ExecuteRequest",
    "ExecuteResult",
    "HomeCommandRequest",
    "HomeSessionScope",
    "OP_DELTA",
    "OP_RESULT",
    "OP_SNAPSHOT",
    "Origin",
    "PANEL_PROFILE",
    "PANEL_PROFILE_PROPERTY",
    "PANEL_REQUEST_TOPIC",
    "PanelArea",
    "PanelCandidate",
    "PanelChange",
    "PanelDelta",
    "PanelDevice",
    "PanelExecute",
    "PanelRequest",
    "PanelScene",
    "PanelSnapshot",
    "PanelSync",
    "Placement",
    "REGISTRY_ERROR_CODES",
    "REQUEST_EXECUTE",
    "REQUEST_SYNC",
    "Registry",
    "RegistryError",
    "SCENE_COMMAND",
    "SCENE_KIND",
    "SCENE_TRAIT",
    "SCHEMA_VERSION",
    "Scene",
    "SmartHomeError",
    "TRAIT_COMMANDS",
    "TRAIT_STATE",
    "VoiceResult",
    "device_type",
    "initial_state",
    "panel_request",
    "validate_command",
    "validate_execute_result",
    "validate_state",
]
