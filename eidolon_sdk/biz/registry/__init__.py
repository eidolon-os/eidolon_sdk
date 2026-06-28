"""Registry domain contracts.

This package is intentionally storage-agnostic. It must not import db, kv, or
adapter modules.
"""

from .models import (
    CompanionRef,
    DeviceBindingRecord,
    DeviceRegistryRecord,
    OwnerRef,
)
from .ports import (
    CompanionStore,
    DeviceBindingStore,
    DeviceStore,
    OwnerStore,
)
from .settings import (
    REGISTRY_DB_ENV,
    default_registry_db_path,
    resolve_registry_db_path,
)

__all__ = [
    "CompanionRef",
    "CompanionStore",
    "DeviceBindingRecord",
    "DeviceBindingStore",
    "DeviceRegistryRecord",
    "DeviceStore",
    "OwnerRef",
    "OwnerStore",
    "REGISTRY_DB_ENV",
    "default_registry_db_path",
    "resolve_registry_db_path",
]
