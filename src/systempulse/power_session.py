from __future__ import annotations

import math

from systempulse.energy import EnergyIntegration, PowerEnergyAccumulator
from systempulse.models import PowerSessionStats, SystemSnapshot


class PowerSessionTracker:
    """Derive live-session power statistics from supplied snapshots."""

    def __init__(self) -> None:
        self._started_monotonic: float | None = None
        self._session_duration_seconds = 0.0
        self._estimated_wall = PowerEnergyAccumulator()
        self._actual_wall = PowerEnergyAccumulator()
        self._peak_estimated_wall_watts: float | None = None
        self._peak_actual_wall_watts: float | None = None
        self._current_cpu_package_watts: float | None = None
        self._current_gpu_total_watts: float | None = None
        self._current_cpu_gpu_watts: float | None = None
        self._current_estimated_system_watts: float | None = None
        self._current_estimated_wall_watts: float | None = None
        self._current_actual_wall_watts: float | None = None

    def observe(
        self,
        snapshot: SystemSnapshot,
        sampled_monotonic: float,
    ) -> PowerSessionStats:
        """Observe an authoritative snapshot at an explicit monotonic timestamp."""
        if self._started_monotonic is None:
            self._started_monotonic = sampled_monotonic
        else:
            elapsed = sampled_monotonic - self._started_monotonic
            if math.isfinite(elapsed) and elapsed > self._session_duration_seconds:
                self._session_duration_seconds = elapsed

        power = snapshot.power
        self._estimated_wall.observe(
            self._session_duration_seconds,
            power.estimated_wall_watts,
        )
        self._actual_wall.observe(
            self._session_duration_seconds,
            power.actual_wall_watts,
        )

        self._current_cpu_package_watts = _available_watts(power.cpu_package_watts)
        self._current_gpu_total_watts = _available_watts(power.gpu_total_watts)
        self._current_cpu_gpu_watts = _available_watts(power.cpu_gpu_watts)
        self._current_estimated_system_watts = _available_watts(power.estimated_system_watts)
        self._current_estimated_wall_watts = _available_watts(power.estimated_wall_watts)
        self._current_actual_wall_watts = _available_watts(power.actual_wall_watts)
        self._peak_estimated_wall_watts = _updated_peak(
            self._peak_estimated_wall_watts,
            self._current_estimated_wall_watts,
        )
        self._peak_actual_wall_watts = _updated_peak(
            self._peak_actual_wall_watts,
            self._current_actual_wall_watts,
        )
        return self.stats

    @property
    def stats(self) -> PowerSessionStats:
        estimated = self._estimated_wall.result
        actual = self._actual_wall.result
        return PowerSessionStats(
            session_duration_seconds=self._session_duration_seconds,
            current_cpu_package_watts=self._current_cpu_package_watts,
            current_gpu_total_watts=self._current_gpu_total_watts,
            current_cpu_gpu_watts=self._current_cpu_gpu_watts,
            current_estimated_system_watts=self._current_estimated_system_watts,
            current_estimated_wall_watts=self._current_estimated_wall_watts,
            average_estimated_wall_watts=_time_weighted_average(estimated),
            peak_estimated_wall_watts=self._peak_estimated_wall_watts,
            estimated_wall_energy_wh=estimated.energy_wh,
            estimated_wall_observed_duration_seconds=estimated.observed_duration_seconds,
            current_actual_wall_watts=self._current_actual_wall_watts,
            average_actual_wall_watts=_time_weighted_average(actual),
            peak_actual_wall_watts=self._peak_actual_wall_watts,
            actual_wall_energy_wh=actual.energy_wh,
            actual_wall_observed_duration_seconds=actual.observed_duration_seconds,
        )


def _available_watts(watts: float | None) -> float | None:
    if watts is None or not math.isfinite(watts) or watts < 0.0:
        return None
    return watts


def _updated_peak(current: float | None, watts: float | None) -> float | None:
    if watts is None:
        return current
    if current is None or watts > current:
        return watts
    return current


def _time_weighted_average(integration: EnergyIntegration) -> float | None:
    if integration.observed_duration_seconds <= 0.0:
        return None
    return integration.energy_wh * 3600.0 / integration.observed_duration_seconds
