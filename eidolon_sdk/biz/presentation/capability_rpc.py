"""Versioned, platform-neutral device execution over LiveKit RPC."""

from typing import Any, Literal
from pydantic import Field
from . import Contract, Identifier

PROFILE = "eidolon.motion.v1"
REGISTRY_PROFILE = "eidolon.motion.v2"
INVOKE_V2 = "eidolon.capability.invoke.v2"
INVOKE = "eidolon.capability.invoke.v1"
STATUS = "eidolon.execution.status.v1"
CANCEL = "eidolon.execution.cancel.v1"


class ExecutionScope(Contract):
    execution_id: Identifier
    session_id: Identifier
    policy_revision: int = Field(strict=True, ge=1)


class CapabilityInvocation(ExecutionScope):
    protocol_version: Literal[1] = 1
    capability: str = Field(min_length=1, max_length=128)
    capability_version: Literal[1] = 1
    arguments: dict[str, Any]
    expires_at_ms: int = Field(strict=True, gt=0)
    max_duration_ms: int = Field(strict=True, ge=1, le=30000)


class RegisteredInvocation(CapabilityInvocation):
    protocol_version: Literal[2] = 2
    capability_version: int = Field(strict=True, ge=1)
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_set_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding_ref: Identifier


class ExecutionSnapshot(Contract):
    execution_id: Identifier
    state: Literal["accepted", "running", "completed", "cancelled", "failed", "rejected"]
    sequence: int = Field(strict=True, ge=0)
    completion_basis: Literal["unconfirmed", "software_sequence", "configuration_applied"] = (
        "unconfirmed"
    )
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


def definitions() -> dict[str, dict]:
    empty = {"type": "object", "properties": {}, "additionalProperties": False}
    repeats = {
        "type": "object",
        "properties": {"repeats": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1}},
        "additionalProperties": False,
    }
    return {
        "motion.stop": {
            "description": "停止当前身体动作并关闭自动随声摆动。Does not stop speech or claim physical emergency stop.",
            "input_schema": empty,
        },
        "motion.nod": {
            "description": "点头。Only an explicit request, not quoted, negated or hypothetical. Repeat 1–3 times.",
            "input_schema": repeats,
        },
        "motion.shake": {
            "description": "摇头。Execute an explicitly requested head shake, repeat 1–3 times.",
            "input_schema": repeats,
        },
        "motion.look": {
            "description": "看向指定方向或回正。Directions are robot-relative, not the observer's.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["left", "right", "up", "down", "front"],
                    }
                },
                "required": ["direction"],
                "additionalProperties": False,
            },
        },
        "motion.catalog": {
            "description": "List the installed, approved body-expression clips and their actual effects before choosing motion.play.",
            "input_schema": empty,
        },
        "motion.play": {
            "description": "Play an installed body-expression clip returned by motion.catalog. A body expression is not a face smile or audible laughter. Never invent clip IDs.",
            "input_schema": {
                "type": "object",
                "properties": {"clip_id": {"type": "string", "minLength": 1, "maxLength": 96}},
                "required": ["clip_id"],
                "additionalProperties": False,
            },
        },
        "behavior.speech_motion": {
            "description": "Enable or disable subtle motion driven by assistant playback. This changes a setting, not a completed physical gesture.",
            "input_schema": {
                "type": "object",
                "properties": {"enabled": {"type": "boolean"}},
                "required": ["enabled"],
                "additionalProperties": False,
            },
        },
    }


def actions(names=None) -> list[dict]:
    return [
        {
            "name": name,
            "version": 1,
            "input_schema": value["input_schema"],
            "output_schema": {"type": "object"},
            "idempotent": name in {"motion.catalog", "behavior.speech_motion"},
        }
        for name, value in definitions().items()
        if names is None or name in names
    ]
