"""Registry domain contracts.

This package is intentionally storage-agnostic. It must not import db, kv, or
adapter modules.
"""

from .models import (
    AgentMetadataRecord,
    ConsolidatorConfig,
    DeviceBindingRecord,
    DeviceRegistryRecord,
    TenantSpec,
    UserRegistryRecord,
    UserSpec,
)
from .ports import (
    AgentMetadataStore,
    DeviceBindingStore,
    DeviceStore,
    TenantStore,
    UserStore,
)
from .settings import (
    REGISTRY_DB_ENV,
    default_registry_db_path,
    resolve_registry_db_path,
)

__all__ = [
    "ConsolidatorConfig",
    "AgentMetadataRecord",
    "AgentMetadataStore",
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
