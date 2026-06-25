"""Compatibility exports for :mod:`eidolon_sdk.biz.admin.client`."""

from eidolon_sdk.biz.admin.client import (
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
    unwrap_detail,
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
    "unwrap_detail",
]
