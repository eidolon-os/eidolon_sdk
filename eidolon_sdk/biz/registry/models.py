"""Registry domain models.

These models describe stable registry data contracts. They do not know where
the data is stored.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from .ids import validate_registry_id


class ConsolidatorConfig(BaseModel):
    """Per-user memory consolidator settings."""

    enabled: bool = True
    interval_hours: float = Field(6.0, gt=0)
    window_days: int = Field(30, gt=0)
    min_drawers: int = Field(3, ge=1)
    min_confidence: float = Field(0.6, ge=0.0, le=1.0)


class TenantSpec(BaseModel):
    """Stable persisted tenant shape."""

    tenant_id: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    created_at: datetime

    @field_validator("tenant_id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        return validate_registry_id(v, field_name="tenant_id")


class UserSpec(BaseModel):
    """Stable user spec exposed to execution projects and admin API callers."""

    user_id: str = Field(..., min_length=1, max_length=64)
    tenant_id: str = Field("default", min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    enabled: bool = True
    memory_port: int = Field(0, ge=0, le=65535)
    palace_path: str = ""
    consolidator: ConsolidatorConfig = Field(default_factory=ConsolidatorConfig)
    created_at: datetime

    @field_validator("user_id")
    @classmethod
    def _check_user_id(cls, v: str) -> str:
        return validate_registry_id(v, field_name="user_id")

    @field_validator("tenant_id")
    @classmethod
    def _check_tenant_id(cls, v: str) -> str:
        return validate_registry_id(v, field_name="tenant_id")


class UserRegistryRecord(BaseModel):
    """Full persisted registry row for a user.

    `active_agent_id` is deliberately kept out of `UserSpec` because admin's
    HTTP view exposes it as routing metadata beside the spec.
    """

    user_id: str = Field(..., min_length=1, max_length=64)
    tenant_id: str = Field("default", min_length=1, max_length=64)
    active_agent_id: str | None = None
    display_name: str = ""
    enabled: bool = True
    palace_path: str = ""
    memory_port: int = Field(0, ge=0, le=65535)
    consolidator: ConsolidatorConfig = Field(default_factory=ConsolidatorConfig)
    created_at: str = ""

    @field_validator("user_id")
    @classmethod
    def _check_user_id(cls, v: str) -> str:
        return validate_registry_id(v, field_name="user_id")

    @field_validator("tenant_id")
    @classmethod
    def _check_tenant_id(cls, v: str) -> str:
        return validate_registry_id(v, field_name="tenant_id")


class DeviceRegistryRecord(BaseModel):
    """Full persisted registry row for a physical device.

    Device ids are hardware/client generated and may be MAC addresses, so they
    intentionally do not use the stricter registry id validator.
    """

    device_id: str = Field(..., min_length=1, max_length=128)
    name: str = ""
    kind: str = "unknown"
    enabled: bool = True
    psk_hash: str | None = None
    paired: bool = False
    approved: bool = False
    approved_at: str | None = None
    created_at: str = ""
    last_seen: str = ""
    metadata: dict = Field(default_factory=dict)


class DeviceBindingRecord(BaseModel):
    """Admin-owned pointer from one device to one agent."""

    device_id: str = Field(..., min_length=1, max_length=128)
    agent_id: str = Field(..., min_length=1, max_length=128)
    bound_at: str
    interaction_mode: str | None = None


class AgentMetadataRecord(BaseModel):
    """Admin-owned metadata that resolves flat agent ids to runtime context."""

    agent_id: str = Field(..., min_length=1, max_length=128)
    tenant_id: str = Field("default", min_length=1, max_length=64)
    user_id: str = Field(..., min_length=1, max_length=64)
    template_id: str = Field(..., min_length=1, max_length=128)
    template_revision: int = 1
    display_name: str = ""
    created_at: str = ""

    @field_validator("tenant_id")
    @classmethod
    def _check_agent_tenant_id(cls, v: str) -> str:
        return validate_registry_id(v, field_name="tenant_id")

    @field_validator("user_id")
    @classmethod
    def _check_agent_user_id(cls, v: str) -> str:
        return validate_registry_id(v, field_name="user_id")
