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
    required_output: Literal["speech", "motion", "expression", "dialogue_text", "audio_cue"]
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

    def accept(self, names, snapshot, *, conversation_id, outputs):
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
        return frozenset(n for n in names if outputs.get(self.get(n).required_output) is True)


@lru_cache(maxsize=1)
def installed_registry():
    from .motion import definitions as motion
    from .music import definitions as music

    registry = CapabilityRegistry()
    # Composition only: each package owns its definitions. Generic layers never enumerate names.
    for package in (music, motion):
        for definition in package():
            registry.register(definition)
    for entry in entry_points(group="eidolon.capabilities"):
        for definition in entry.load()():
            registry.register(definition)
    return registry


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
