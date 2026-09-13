"""Infrastructure adapters for the transport-neutral audit contract."""

from .nats import (
    AuditNatsPublisherSettings,
    JetStreamAuditPublisher,
    require_audit_transport,
)
from .stream import (
    AUDIT_MAX_AGE,
    AUDIT_MAX_BYTES,
    AUDIT_STREAM_NAME,
    AUDIT_SUBJECT_PREFIX,
    audit_subject,
    ensure_audit_stream,
)

__all__ = [
    "AUDIT_MAX_AGE",
    "AUDIT_MAX_BYTES",
    "AUDIT_STREAM_NAME",
    "AUDIT_SUBJECT_PREFIX",
    "AuditNatsPublisherSettings",
    "JetStreamAuditPublisher",
    "audit_subject",
    "ensure_audit_stream",
    "require_audit_transport",
]
