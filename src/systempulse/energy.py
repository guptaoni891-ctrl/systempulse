"""Pure trapezoidal integration for timestamped optional power telemetry.

Only consecutive finite, non-negative watt readings with a positive finite time
interval contribute energy. Missing, negative, or non-finite readings break
continuity, so integration never bridges a telemetry gap.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeGuard


@dataclass(frozen=True, slots=True)
class EnergyIntegration:
    """Consumed energy and the duration covered by valid power intervals."""

    energy_wh: float
    observed_duration_seconds: float


class PowerEnergyAccumulator:
    """Incrementally integrate watt readings at elapsed numeric timestamps."""

    def __init__(self) -> None:
        self._energy_wh = 0.0
        self._observed_duration_seconds = 0.0
        self._previous: tuple[float, float | None] | None = None

    @property
    def energy_wh(self) -> float:
        return self._energy_wh

    @property
    def observed_duration_seconds(self) -> float:
        return self._observed_duration_seconds

    @property
    def result(self) -> EnergyIntegration:
        return EnergyIntegration(
            energy_wh=self._energy_wh,
            observed_duration_seconds=self._observed_duration_seconds,
        )

    def observe(self, timestamp: float, watts: float | None) -> None:
        """Observe a reading without bridging invalid power or time intervals."""
        if self._previous is not None:
            previous_timestamp, previous_watts = self._previous
            duration = timestamp - previous_timestamp
            if (
                duration > 0.0
                and math.isfinite(duration)
                and _is_usable_power(previous_watts)
                and _is_usable_power(watts)
            ):
                self._energy_wh += ((previous_watts + watts) / 2.0) * duration / 3600.0
                self._observed_duration_seconds += duration
        self._previous = timestamp, watts


def integrate_power_samples(
    samples: Iterable[tuple[float, float | None]],
) -> EnergyIntegration:
    """Integrate optional watt readings sampled at elapsed numeric seconds."""
    accumulator = PowerEnergyAccumulator()
    for timestamp, watts in samples:
        accumulator.observe(timestamp, watts)
    return accumulator.result


def integrate_datetime_power_samples(
    samples: Iterable[tuple[datetime, float | None]],
) -> EnergyIntegration:
    """Integrate optional watt readings sampled at datetime timestamps."""
    accumulator = PowerEnergyAccumulator()
    origin: datetime | None = None
    for timestamp, watts in samples:
        if origin is None:
            origin = timestamp
        accumulator.observe((timestamp - origin).total_seconds(), watts)
    return accumulator.result


def _is_usable_power(watts: float | None) -> TypeGuard[float]:
    """Return whether wattage represents finite, non-negative consumption."""
    return watts is not None and math.isfinite(watts) and watts >= 0.0
