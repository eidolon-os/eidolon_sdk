"""Installed contracts and versioned session projection, independent of transport.

Only locally installed packages can register definitions. Wire declarations are
references to those definitions, never remotely supplied schemas or code.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.metadata import entry_points
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eidolon_sdk.biz.body.manifest import _validate_schema, validate_capability_arguments


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def check_schema(schema, *, root=True):
    # Bounded common subset, plus local alternatives (no remote refs/evaluation).
    plain = {k: v for k, v in schema.items() if k != "anyOf"}
    _validate_schema(plain, field="capability_schema", require_object=root)
    if "anyOf" in schema:
        alternatives = schema["anyOf"]
        if not isinstance(alternatives, list) or not 1 <= len(alternatives) <= 16:
            raise ValueError("invalid schema alternatives")
        for branch in alternatives:
            if not isinstance(branch, dict) or "anyOf" in branch:
                raise ValueError("unsupported nested alternative")
            _validate_schema({**plain, **branch}, field="alternative", require_object=root)


def validate(schema, value):
    json.dumps(value, allow_nan=False)
    error = validate_capability_arguments(schema, value)
    if error:
        raise ValueError(error)
    if "anyOf" in schema and not any(
        validate_capability_arguments({**schema, **branch}, value) is None
        for branch in schema["anyOf"]
    ):
        raise ValueError("arguments match no alternative")


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", max_length=128)
    version: int = Field(default=1, ge=1, strict=True)
    llm_name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$", max_length=64)
    description: str = Field(min_length=1, max_length=2048)
    input_schema: dict[str, Any]
    result_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    # What the Owner must have allowed for a session to use this: one response
    # output, or one input. Exactly one of the two.
    required_output: Literal["speech", "motion", "expression", "dialogue_text", "audio_cue"] | None = None
    required_input: Literal["camera"] | None = None
    # False: the Agent uses it on the model's behalf and never offers it as a tool.
    model_tool: bool = True
    # True: the Owner's own app may invoke it on a device outside any session,
    # through the channel the Host holds to that device. Not a policy gate: the
    # Owner is the authority the output gates above exist to answer to.
    owner_control: bool = False
    execution_location: Literal["channel", "device"]
    body_control: bool = False
    side_effect: bool = True
    idempotent: bool = False
    timeout_s: float = Field(default=30, gt=0, le=120)
    legacy_channel: bool = False
    preempts_active: bool = False
    # JSON object path in a successful tool result to reusable resource descriptors.
    # Retained only in the current session, never as completion evidence.
    reference_result_path: tuple[str, ...] = ()
    supports_background: bool = False
    # Opt-in semantic use, not inferred from background execution or a tool name.
    # The Agent may attach this command to a public response without waiting for
    # completion. Transport, authorization and execution remain unchanged.
    supports_response_attachment: bool = False
    resource_preview_arguments: dict[str, Any] | None = None
    completion_basis: Literal["software_sequence", "configuration_applied", "unconfirmed"] = (
        "software_sequence"
    )

    @model_validator(mode="after")
    def schemas(self):
        if self.supports_response_attachment and not self.supports_background:
            raise ValueError("response attachment requires background execution")
        if (self.required_output is None) == (self.required_input is None):
            raise ValueError("a capability requires one output or one input")
        check_schema(self.input_schema)
        check_schema(self.result_schema, root=False)
        return self

    @property
    def contract_digest(self):
        value = self.model_dump(mode="json")
        # An absent optional use is the old contract. Do not invalidate music
        # and other unmodified packages merely by adding this SDK field.
        if not self.supports_response_attachment:
            value.pop("supports_response_attachment")
        # Likewise the input gate and the tool switch: absent means the contract
        # every installed device already agreed on.
        if self.required_input is None:
            value.pop("required_input")
        if self.model_tool:
            value.pop("model_tool")
        if not self.owner_control:
            value.pop("owner_control")
        return digest(value)

    def action(self):
        return {
            "name": self.name,
            "version": self.version,
            "input_schema": self.input_schema,
            "output_schema": self.result_schema,
            "idempotent": self.idempotent,
        }


class CapabilityRegistry:
    def __init__(self):
        self._definitions = {}

    def register(self, definition):
        definition = CapabilityDefinition.model_validate(definition).model_copy(deep=True)
        if definition.name in self._definitions:
            if self._definitions[definition.name] != definition:
                raise ValueError("conflicting capability contract")
            return
        if any(d.llm_name == definition.llm_name for d in self._definitions.values()):
            raise ValueError("conflicting model tool name")
        self._definitions[definition.name] = definition

    def get(self, name):
        return self._definitions[name].model_copy(deep=True)

    def __contains__(self, name):
        return name in self._definitions

    def definitions(self):
        return tuple(self.get(name) for name in sorted(self._definitions))

    def snapshot(self, names, *, conversation_id, policy_revision=0):
        contracts = [
            {
                "name": d.name,
                "version": d.version,
                "digest": d.contract_digest,
                "location": d.execution_location,
            }
            for d in (self.get(n) for n in sorted(names))
        ]
        body = {
            "version": 1,
            "conversation_id": conversation_id,
            "policy_revision": policy_revision,
            "contracts": contracts,
        }
        return {**body, "revision": digest(body)}

    def accept(self, names, snapshot, *, conversation_id, outputs, inputs=None):
        names = frozenset(names)
        if snapshot is None:
            # Old callers see only contracts explicitly declaring legacy support.
            return frozenset(n for n in names if n in self and self.get(n).legacy_channel)
        if not isinstance(snapshot, dict) or len(names) > 64:
            raise ValueError("invalid capability set")
        # Protobuf Struct represents numeric values as doubles. Normalize before hashing.
        normalized = dict(snapshot)

        def wire_integer(value):
            if (
                type(value) not in (int, float)
                or not float(value).is_integer()
                or abs(value) > 2**53 - 1
            ):
                raise ValueError("invalid integer in capability set")
            return int(value)

        normalized["version"] = wire_integer(normalized.get("version", -1))
        normalized["policy_revision"] = wire_integer(normalized.get("policy_revision", -1))
        normalized["contracts"] = [
            {**r, "version": wire_integer(r["version"])} for r in normalized.get("contracts", [])
        ]
        expected = self.snapshot(
            names, conversation_id=conversation_id, policy_revision=normalized["policy_revision"]
        )
        if normalized != expected:
            raise ValueError("stale or unrecognized capability set")
        return self.permitted(names, outputs=outputs, inputs=inputs)

    def permitted(self, names, *, outputs, inputs=None):
        """Which of these installed contracts the Owner's selection lets a session use.

        One rule for the Agent accepting a session's set and for the Channel
        building it: a capability gated on an output needs that output selected,
        one gated on the camera needs capture allowed.
        """

        inputs = inputs or {}

        def allowed(definition):
            if definition.required_input == "camera":
                return inputs.get("camera") == "capture"
            return outputs.get(definition.required_output) is True

        return frozenset(n for n in names if n in self and allowed(self.get(n)))


@lru_cache(maxsize=1)
def installed_registry():
    from .camera import definitions as camera
    from .device_settings import definitions as device_settings
    from .motion import definitions as motion
    from .music import definitions as music
    from .vision import definitions as vision

    registry = CapabilityRegistry()
    # Composition only: each package owns its definitions. Generic layers never enumerate names.
    for package in (music, motion, camera, vision, device_settings):
        for definition in package():
            registry.register(definition)
    for entry in entry_points(group="eidolon.capabilities"):
        for definition in entry.load()():
            registry.register(definition)
    return registry


@lru_cache(maxsize=1)
def _installed_properties() -> str:
    from .device_settings import properties as device_settings

    declared: dict[str, dict] = {}
    # Composition only, like the registry: each package owns its declarations.
    for package in (device_settings,):
        for name, declaration in package().items():
            if name in declared and declared[name] != declaration:
                raise ValueError("conflicting property declaration")
            check_schema({"type": "object", "properties": {"value": declaration["schema"]}})
            declared[name] = declaration
    return json.dumps(declared, sort_keys=True)


def installed_properties() -> dict[str, dict]:
    """Observable Manifest properties this Host can read, keyed by name.

    The same rule as capabilities: a device's property declaration is read only
    when it equals one an installed package defines, so the schema a reported
    value is checked against is the Host's and never the device's.
    """

    return json.loads(_installed_properties())


def declared_observable_properties(manifest) -> dict[str, dict]:
    """The installed observable properties this Manifest declares, name to schema."""

    installed = installed_properties()
    return {
        entry["name"]: dict(entry["schema"])
        for entry in manifest.get("properties", ()) or ()
        if isinstance(entry, dict) and installed.get(entry.get("name")) == entry
    }


def check_property_value(schema, value) -> None:
    """Refuse a reported value its declared schema does not admit."""

    json.dumps(value, allow_nan=False)
    error = validate_capability_arguments(
        {"type": "object", "properties": {"value": schema}, "required": ["value"]},
        {"value": value},
    )
    if error:
        raise ValueError(error)


def decode_arguments(schema, value):
    """Recover schema integers after protobuf Struct's IEEE-754 number encoding."""
    if schema.get("type") == "integer" and type(value) is float:
        if not value.is_integer() or abs(value) > 2**53 - 1:
            raise ValueError("integer is not represented exactly")
        return int(value)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        return {k: decode_arguments(properties.get(k, {}), v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode_arguments(schema.get("items", {}), v) for v in value]
    return value
