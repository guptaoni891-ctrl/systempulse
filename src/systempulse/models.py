from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class GPUStats:
    name: str
    usage_percent: float
    temperature_celsius: float
    vram_used_mib: float
    vram_total_mib: float
    power_watts: float | None


@dataclass(frozen=True, slots=True)
class NetworkStats:
    bytes_sent: int
    bytes_received: int


@dataclass(frozen=True, slots=True)
class NetworkSpeed:
    upload_bytes_per_second: float
    download_bytes_per_second: float


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    timestamp: datetime
    cpu_usage_percent: float
    ram_usage_percent: float
    ram_used_bytes: int
    ram_total_bytes: int
    disk_usage_percent: float
    disk_used_bytes: int
    disk_total_bytes: int
    cpu_temperature_celsius: float | None
    network: NetworkStats
    gpus: tuple[GPUStats, ...]


@dataclass(frozen=True, slots=True)
class ProcessStats:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
