"""Admin HTTP contracts shared by Eidolon Python projects."""

from .client import (
    AdminClient,
    AdminClientError,
    AdminNotFound,
    AdminPrecondition,
    AdminResolveClient,
    AdminResolveError,
    AdminResolveNotFound,
    AdminResolvePrecondition,
    AdminResolveUnreachable,
    AdminResolveUpstream,
    AdminUnreachable,
    AdminUpstreamError,
    ResolvedContext,
)

__all__ = [
    "AdminClient",
    "AdminClientError",
    "AdminNotFound",
    "AdminPrecondition",
    "AdminResolveClient",
    "AdminResolveError",
    "AdminResolveNotFound",
    "AdminResolvePrecondition",
    "AdminResolveUnreachable",
    "AdminResolveUpstream",
    "AdminUnreachable",
    "AdminUpstreamError",
    "ResolvedContext",
]
