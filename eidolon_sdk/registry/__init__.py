"""Compatibility exports for :mod:`eidolon_sdk.biz.registry`.

This package is intentionally storage-agnostic. It must not import db, kv, or
adapter modules.
"""

from eidolon_sdk.biz.registry import (
    AgentMetadataRecord,
    AgentMetadataStore,
    ConsolidatorConfig,
    DeviceBindingRecord,
    DeviceBindingStore,
    DeviceRegistryRecord,
    DeviceStore,
    REGISTRY_DB_ENV,
    TenantSpec,
    TenantStore,
    UserRegistryRecord,
    UserSpec,
    UserStore,
    default_registry_db_path,
    resolve_registry_db_path,
)

__all__ = [
    "AgentMetadataRecord",
    "AgentMetadataStore",
    "ConsolidatorConfig",
    "DeviceBindingRecord",
    "DeviceBindingStore",
    "DeviceRegistryRecord",
    "DeviceStore",
    "REGISTRY_DB_ENV",
    "TenantSpec",
    "TenantStore",
    "UserRegistryRecord",
    "UserSpec",
    "UserStore",
    "default_registry_db_path",
    "resolve_registry_db_path",
]
