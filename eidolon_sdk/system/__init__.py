"""Machine-scoped contracts shared by Host system producers and consumers."""

from .host_links import (
    MANAGEMENT_NETWORKS_VARIABLE,
    HostLinkDeclarationError,
    declared_management_networks,
    on_product_link,
)

__all__ = [
    "MANAGEMENT_NETWORKS_VARIABLE",
    "HostLinkDeclarationError",
    "declared_management_networks",
    "on_product_link",
]
