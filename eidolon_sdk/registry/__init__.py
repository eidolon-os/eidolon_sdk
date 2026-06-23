"""Registry domain contracts.

This package is intentionally storage-agnostic. It must not import db, kv, or
adapter modules.
"""

from .models import ConsolidatorConfig, TenantSpec, UserRegistryRecord, UserSpec
from .ports import TenantStore, UserStore
from .settings import (
    REGISTRY_DB_ENV,
    default_registry_db_path,
    resolve_registry_db_path,
)

__all__ = [
    "ConsolidatorConfig",
    "REGISTRY_DB_ENV",
    "TenantSpec",
    "TenantStore",
    "UserRegistryRecord",
    "UserSpec",
    "UserStore",
    "default_registry_db_path",
    "resolve_registry_db_path",
]
