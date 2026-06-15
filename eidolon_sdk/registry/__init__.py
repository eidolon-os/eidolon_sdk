"""Registry domain contracts.

This package is intentionally storage-agnostic. It must not import db, kv, or
adapter modules.
"""

from .models import ConsolidatorConfig, TenantSpec, UserRegistryRecord, UserSpec
from .ports import TenantStore, UserStore

__all__ = [
    "ConsolidatorConfig",
    "TenantSpec",
    "TenantStore",
    "UserRegistryRecord",
    "UserSpec",
    "UserStore",
]

