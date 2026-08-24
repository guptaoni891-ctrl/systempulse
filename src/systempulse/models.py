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


class AlertSeverity(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertTransition(StrEnum):
    OPENED = "opened"
    ESCALATED = "escalated"
    DEESCALATED = "deescalated"
    RESOLVED = "resolved"


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


def _normalized_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AlertEvent:
    timestamp: datetime
    metric: str
    label: str
    severity: AlertSeverity
    transition: AlertTransition
    current_value: float
    threshold: float
    unit: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timestamp",
            _normalized_utc(self.timestamp, "AlertEvent timestamp"),
        )


@dataclass(frozen=True, slots=True)
class ActiveAlert:
    metric: str
    label: str
    severity: AlertSeverity
    current_value: float
    threshold: float
    unit: str
    opened_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "opened_at",
            _normalized_utc(self.opened_at, "ActiveAlert opened_at"),
        )
        object.__setattr__(
            self,
            "updated_at",
            _normalized_utc(self.updated_at, "ActiveAlert updated_at"),
        )


@dataclass(frozen=True, slots=True)
class ProcessStats:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
