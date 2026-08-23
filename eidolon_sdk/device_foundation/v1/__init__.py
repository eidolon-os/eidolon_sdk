"""Device Foundation V1 bindings and host-independent core ports."""

from .authority_locator import (
    AuthorityEndpoint,
    AuthorityLocator,
    AuthorityLocatorError,
    AuthorityLocatorPort,
    LogicalAuthority,
    OwnerDomainDescriptor,
    OwnerDomainTrustAnchor,
    descriptor_key_id,
    sign_descriptor,
    verify_descriptor,
)
from .lifecycle import (
    ActorRef,
    ClaimEventPage,
    ClaimEventRecord,
    DeviceRef,
    OwnerAuthorizationContext,
    RemovalIntent,
    RevokeClaim,
    RevokeClaimResult,
)

__all__ = [
    "AuthorityEndpoint",
    "AuthorityLocator",
    "AuthorityLocatorError",
    "AuthorityLocatorPort",
    "LogicalAuthority",
    "OwnerDomainDescriptor",
    "OwnerDomainTrustAnchor",
    "descriptor_key_id",
    "sign_descriptor",
    "verify_descriptor",
    "ActorRef",
    "ClaimEventPage",
    "ClaimEventRecord",
    "DeviceRef",
    "OwnerAuthorizationContext",
    "RemovalIntent",
    "RevokeClaim",
    "RevokeClaimResult",
]
