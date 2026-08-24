from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


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


class DiagnosticKind(StrEnum):
    UNAVAILABLE = "unavailable"
    COMMAND_MISSING = "command_missing"
    TIMEOUT = "timeout"
    EXECUTION_FAILED = "execution_failed"
    MALFORMED_RESULT = "malformed_result"
    INVALID_INTERVAL = "invalid_interval"


@dataclass(frozen=True, slots=True)
class CollectionDiagnostic:
    collector: str
    kind: DiagnosticKind
    message: str


@dataclass(frozen=True, slots=True)
class CoreMetrics:
    cpu_usage_percent: float
    ram_usage_percent: float
    ram_used_bytes: int
    ram_total_bytes: int
    disk_usage_percent: float
    disk_used_bytes: int
    disk_total_bytes: int
    cpu_temperature_celsius: float | None
    network: NetworkStats
    diagnostics: tuple[CollectionDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class GPUCollection:
    gpus: tuple[GPUStats, ...]
    diagnostics: tuple[CollectionDiagnostic, ...] = ()


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
    network_speed: NetworkSpeed
    gpus: tuple[GPUStats, ...]
    diagnostics: tuple[CollectionDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("SystemSnapshot timestamp must be timezone-aware.")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class ProcessStats:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
