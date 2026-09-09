"""Host System V1 wire bindings.

The machine publishes observations here; product-facing interpretation stays at
the ingress that knows what a reading means to the person using that Host.
"""

from .host_monitor import HostMonitorWire

from .host_vitals import (
    HOST_VITALS_CONTRACT,
    HOST_VITALS_OPERATION,
    HostVitalsWire,
    MeasurementWire,
)

__all__ = [
    "HostMonitorWire",
    "HOST_VITALS_CONTRACT",
    "HOST_VITALS_OPERATION",
    "HostVitalsWire",
    "MeasurementWire",
]
