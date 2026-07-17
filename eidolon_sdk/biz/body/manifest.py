"""Strict dynamic capability declarations for online body devices.

This module deliberately accepts one wire shape.  It is not a compatibility
parser and it does not merge device declarations with a platform allow-list.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_CAPABILITIES_PER_DEVICE = 64
MAX_CAPABILITY_SCHEMA_BYTES = 16 * 1024
MAX_SCHEMA_DEPTH = 8
MAX_SCHEMA_PROPERTIES = 64
MAX_SCHEMA_ENUM_VALUES = 64

_CAPABILITY_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_JSON_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_SCHEMA_KEYS = {
    "type",
    "description",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
    "format",
    "default",
}


class CapabilityDeclaration(BaseModel):
    """One device-provided execution contract.

    Authorization, risk, confirmation, QoS and availability are platform facts
    and therefore intentionally absent from this model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    name: str = Field(min_length=3, max_length=128)
    version: int = Field(ge=1, le=65535)
    description: str = Field(min_length=1, max_length=512)
    input_schema: dict[str, Any]
    result_schema: dict[str, Any]

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _CAPABILITY_NAME.fullmatch(value):
            raise ValueError(
                "capability name must be a lowercase dotted namespace, "
                "for example camera.capture"
            )
        return value

    @field_validator("input_schema")
    @classmethod
    def _valid_input_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_schema(value, field="input_schema", require_object=True)
        return value

    @field_validator("result_schema")
    @classmethod
    def _valid_result_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_schema(value, field="result_schema", require_object=False)
        return value


class CapabilityManifest(BaseModel):
    """The complete capability set declared by one registration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capabilities: tuple[CapabilityDeclaration, ...] = Field(
        default_factory=tuple,
        max_length=MAX_CAPABILITIES_PER_DEVICE,
    )

    @model_validator(mode="after")
    def _unique_contracts(self) -> "CapabilityManifest":
        seen: set[str] = set()
        for capability in self.capabilities:
            if capability.name in seen:
                raise ValueError(f"duplicate capability declaration: {capability.name}")
            seen.add(capability.name)
        return self


def validate_capability_arguments(
    schema: dict[str, Any],
    value: Any,
    *,
    path: str = "$",
) -> str | None:
    """Validate a value against the supported declaration schema subset."""

    expected = schema.get("type")
    if expected is not None and not _matches_json_type(value, expected):
        return f"{path} expected {expected}"
    if "const" in schema and value != schema["const"]:
        return f"{path} must equal the declared constant"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of the declared enum values"

    if expected == "object":
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        missing = [name for name in required if name not in value]
        if missing:
            return f"{path} missing required: {', '.join(missing)}"
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                return f"{path} unexpected properties: {', '.join(extra)}"
        for name, child_schema in properties.items():
            if name not in value:
                continue
            error = validate_capability_arguments(
                child_schema,
                value[name],
                path=f"{path}.{name}",
            )
            if error:
                return error

    if expected == "array":
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            return f"{path} must contain at least {minimum} items"
        if isinstance(maximum, int) and len(value) > maximum:
            return f"{path} must contain at most {maximum} items"
        child_schema = schema.get("items")
        if child_schema is not None:
            for index, item in enumerate(value):
                error = validate_capability_arguments(
                    child_schema,
                    item,
                    path=f"{path}[{index}]",
                )
                if error:
                    return error

    if expected == "string":
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            return f"{path} must contain at least {minimum} characters"
        if isinstance(maximum, int) and len(value) > maximum:
            return f"{path} must contain at most {maximum} characters"
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            return f"{path} does not match the declared pattern"

    if expected in {"integer", "number"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        exclusive_maximum = schema.get("exclusiveMaximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return f"{path} must be greater than or equal to {minimum}"
        if isinstance(maximum, (int, float)) and value > maximum:
            return f"{path} must be less than or equal to {maximum}"
        if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
            return f"{path} must be greater than {exclusive_minimum}"
        if isinstance(exclusive_maximum, (int, float)) and value >= exclusive_maximum:
            return f"{path} must be less than {exclusive_maximum}"
    return None


def _validate_schema(
    schema: dict[str, Any],
    *,
    field: str,
    require_object: bool,
) -> None:
    try:
        encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON serializable") from exc
    if len(encoded) > MAX_CAPABILITY_SCHEMA_BYTES:
        raise ValueError(f"{field} exceeds {MAX_CAPABILITY_SCHEMA_BYTES} bytes")
    if require_object and schema.get("type") != "object":
        raise ValueError(f"{field} root type must be object")
    _validate_schema_node(schema, path=field, depth=0)


def _validate_schema_node(schema: Any, *, path: str, depth: int) -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"{path} must be an object")
    if depth > MAX_SCHEMA_DEPTH:
        raise ValueError(f"{path} exceeds maximum schema depth {MAX_SCHEMA_DEPTH}")
    unknown = sorted(set(schema) - _SCHEMA_KEYS)
    if unknown:
        raise ValueError(f"{path} uses unsupported JSON Schema keywords: {', '.join(unknown)}")

    expected = schema.get("type")
    if expected is not None and expected not in _JSON_TYPES:
        raise ValueError(f"{path}.type is unsupported: {expected!r}")
    description = schema.get("description")
    if description is not None and (
        not isinstance(description, str) or len(description) > 256
    ):
        raise ValueError(f"{path}.description must be a string of at most 256 characters")

    enum = schema.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum:
            raise ValueError(f"{path}.enum must be a non-empty array")
        if len(enum) > MAX_SCHEMA_ENUM_VALUES:
            raise ValueError(f"{path}.enum exceeds {MAX_SCHEMA_ENUM_VALUES} values")

    properties = schema.get("properties")
    if properties is not None:
        if expected != "object" or not isinstance(properties, dict):
            raise ValueError(f"{path}.properties requires type=object")
        if len(properties) > MAX_SCHEMA_PROPERTIES:
            raise ValueError(f"{path}.properties exceeds {MAX_SCHEMA_PROPERTIES} entries")
        for name, child in properties.items():
            if not isinstance(name, str) or not name or len(name) > 128:
                raise ValueError(f"{path}.properties contains an invalid name")
            _validate_schema_node(child, path=f"{path}.properties.{name}", depth=depth + 1)

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise ValueError(f"{path}.required must be an array of strings")
        if len(required) != len(set(required)):
            raise ValueError(f"{path}.required contains duplicates")
        if properties is None or not set(required).issubset(properties):
            raise ValueError(f"{path}.required must reference declared properties")

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool):
        raise ValueError(f"{path}.additionalProperties must be boolean")

    items = schema.get("items")
    if items is not None:
        if expected != "array":
            raise ValueError(f"{path}.items requires type=array")
        _validate_schema_node(items, path=f"{path}.items", depth=depth + 1)


def _matches_json_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[expected]
