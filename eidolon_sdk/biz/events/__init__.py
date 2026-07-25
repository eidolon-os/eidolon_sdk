"""Short-lived owner-scoped device event contracts."""

from .protocol import (
    AMBIENT_PRESENCE_CHANGED_TYPE,
    EVENT_DEFAULT_TTL_MS,
    EVENT_MAX_CLOCK_SKEW_MS,
    EVENT_MAX_BYTES,
    EVENT_SCHEMA_VERSION,
    IDENTITY_OWNER_PRESENCE_CONFIRMED_TYPE,
    AmbientPresenceChanged,
    AmbientPresencePayload,
    DeviceEvent,
    EventSource,
    IdentityOwnerPresenceConfirmed,
    OwnerPresenceConfirmedPayload,
    normalize_device_event,
    parse_device_event,
)

__all__ = [
    "AMBIENT_PRESENCE_CHANGED_TYPE",
    "EVENT_DEFAULT_TTL_MS",
    "EVENT_MAX_CLOCK_SKEW_MS",
    "EVENT_MAX_BYTES",
    "EVENT_SCHEMA_VERSION",
    "IDENTITY_OWNER_PRESENCE_CONFIRMED_TYPE",
    "AmbientPresenceChanged",
    "AmbientPresencePayload",
    "DeviceEvent",
    "EventSource",
    "IdentityOwnerPresenceConfirmed",
    "OwnerPresenceConfirmedPayload",
    "normalize_device_event",
    "parse_device_event",
]
