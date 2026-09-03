from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from systempulse.collector import collect_core_metrics
from systempulse.config import AppConfig
from systempulse.gpu import collect_gpu_stats
from systempulse.models import (
    CollectionDiagnostic,
    CoreMetrics,
    CPUPowerCollection,
    DiagnosticKind,
    GPUCollection,
    NetworkSpeed,
    NetworkStats,
    SystemSnapshot,
)
from systempulse.network import calculate_network_speed, get_network_totals
from systempulse.power import calculate_power_stats, collect_cpu_package_power

CoreCollector = Callable[[AppConfig], CoreMetrics]
GPUCollector = Callable[[], GPUCollection]
NetworkCollector = Callable[[], NetworkStats]
CPUPowerCollector = Callable[[], CPUPowerCollection]
MonotonicClock = Callable[[], float]
WallClock = Callable[[], datetime]
Sleep = Callable[[float], None]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MonitorService:
    """Create authoritative snapshots and retain only prior network sampling state."""

    def __init__(
        self,
        config: AppConfig,
        *,
        include_gpu: bool = True,
        core_collector: CoreCollector | None = None,
        gpu_collector: GPUCollector | None = None,
        network_collector: NetworkCollector | None = None,
        cpu_power_collector: CPUPowerCollector | None = None,
        monotonic: MonotonicClock | None = None,
        wall_clock: WallClock | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        self.config = config
        self.include_gpu = include_gpu
        self._core_collector = core_collector or collect_core_metrics
        self._gpu_collector = gpu_collector or collect_gpu_stats
        self._network_collector = network_collector or get_network_totals
        self._cpu_power_collector = cpu_power_collector or collect_cpu_package_power
        self._monotonic = monotonic or time.monotonic
        self._wall_clock = wall_clock or _utc_now
        self._sleep = sleep or time.sleep
        self._previous_network: NetworkStats | None = None
        self._previous_monotonic: float | None = None

    def sample(self) -> SystemSnapshot:
        core = self._core_collector(self.config)
        sampled_monotonic = self._monotonic()
        timestamp = self._wall_clock()
        diagnostics = list(core.diagnostics)

        network_speed = NetworkSpeed(0.0, 0.0)
        if self._previous_network is not None and self._previous_monotonic is not None:
            elapsed = sampled_monotonic - self._previous_monotonic
            if elapsed > 0:
                network_speed = calculate_network_speed(
                    self._previous_network,
                    core.network,
                    elapsed,
                )
            else:
                diagnostics.append(
                    CollectionDiagnostic(
                        collector="network_rate",
                        kind=DiagnosticKind.INVALID_INTERVAL,
                        message="Network rate interval was not greater than zero; rates are zero.",
                    )
                )

        self._previous_network = core.network
        self._previous_monotonic = sampled_monotonic

        gpu = self._gpu_collector() if self.include_gpu else GPUCollection(gpus=())
        diagnostics.extend(gpu.diagnostics)
        cpu_power = (
            self._cpu_power_collector() if self.config.power.enabled else CPUPowerCollection()
        )
        diagnostics.extend(cpu_power.diagnostics)
        power = calculate_power_stats(
            cpu_power.cpu_package_watts,
            cpu_power.source,
            gpu.gpus,
            self.config.power,
        )

        return SystemSnapshot(
            timestamp=timestamp,
            cpu_usage_percent=core.cpu_usage_percent,
            ram_usage_percent=core.ram_usage_percent,
            ram_used_bytes=core.ram_used_bytes,
            ram_total_bytes=core.ram_total_bytes,
            disk_usage_percent=core.disk_usage_percent,
            disk_used_bytes=core.disk_used_bytes,
            disk_total_bytes=core.disk_total_bytes,
            cpu_temperature_celsius=core.cpu_temperature_celsius,
            network=core.network,
            network_speed=network_speed,
            gpus=gpu.gpus,
            power=power,
            diagnostics=tuple(diagnostics),
        )

    def sample_with_network_rate(self, interval: float = 1.0) -> SystemSnapshot:
        """Ensure a prior counter reading, wait once, then return one complete sample."""
        if self._previous_network is None:
            self._previous_network = self._network_collector()
            self._previous_monotonic = self._monotonic()
        self._sleep(max(float(interval), 0.1))
        return self.sample()
