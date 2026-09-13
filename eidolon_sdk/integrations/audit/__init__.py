"""Infrastructure adapters for the transport-neutral audit contract."""

from .nats import (
    FAILURE_REPORT_EVERY,
    AuditNatsPublisherSettings,
    AuditPublishError,
    JetStreamAuditPublisher,
    require_audit_transport,
    should_report_publish_failure,
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
    "FAILURE_REPORT_EVERY",
    "AuditNatsPublisherSettings",
    "AuditPublishError",
    "JetStreamAuditPublisher",
    "audit_subject",
    "ensure_audit_stream",
    "require_audit_transport",
    "should_report_publish_failure",
]
