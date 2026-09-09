"""Current host telemetry. No time series or command execution surface."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HOST_MONITOR_CONTRACT = "https://contracts.eidolon.live/system/v1/host-monitor.schema.json"


class MonitorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class MonitorCore(MonitorModel):
    core_id: str
    model: str | None = None
    usage_percent: float | None = Field(default=None, ge=0, le=100)
    frequency_mhz: float | None = Field(default=None, ge=0)
    unavailable_reason: str | None = None


class MonitorProcessor(MonitorModel):
    device_id: str
    model: str | None = None
    usage_percent: float | None = Field(default=None, ge=0, le=100)
    temperature_celsius: float | None = None
    cores: tuple[MonitorCore, ...] = ()
    unavailable_reason: str | None = None


class MonitorMemory(MonitorModel):
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    unavailable_reason: str | None = None


class MonitorDisk(MonitorModel):
    path: str
    total_bytes: int | None = Field(default=None, ge=0)
    available_bytes: int | None = Field(default=None, ge=0)
    unavailable_reason: str | None = None


class MonitorProcess(MonitorModel):
    pid: int = Field(ge=1)
    parent_pid: int = Field(ge=0)
    name: str
    state: str
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    rss_bytes: int | None = Field(default=None, ge=0)
    user: str | None = None
    executable: str | None = None
    source_path: str | None = None
    entry_module: str | None = None
    working_directory: str | None = None
    command: str | None = None
    started_at: datetime | None = None
    uptime_seconds: float | None = Field(default=None, ge=0)
    unavailable_reason: str | None = None


class MonitorService(MonitorModel):
    service_id: str
    unit: str | None = None
    state: str
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    memory_bytes: int | None = Field(default=None, ge=0)
    memory_kind: str = "cgroup"
    configuration_path: str | None = None
    working_directory: str | None = None
    user: str | None = None
    main_pid: int | None = None
    exit_code: int | None = None
    processes: tuple[MonitorProcess, ...] = ()
    unavailable_reason: str | None = None


class HostMonitorWire(MonitorModel):
    operation: Literal["system.host-monitor"] = "system.host-monitor"
    observed_at: datetime
    hostname: str
    machine_model: str | None = None
    operating_system: str | None = None
    uptime_seconds: float | None = Field(default=None, ge=0)
    cpu: MonitorProcessor
    npus: tuple[MonitorProcessor, ...] = ()
    npu_unavailable_reason: str | None = None
    memory: MonitorMemory
    disks: tuple[MonitorDisk, ...] = ()
    services: tuple[MonitorService, ...] = ()
    services_unavailable_reason: str | None = None
