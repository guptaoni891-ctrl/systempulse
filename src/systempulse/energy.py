"""Pure trapezoidal integration for timestamped optional power telemetry.

Only consecutive finite, non-negative watt readings with a positive finite time
interval contribute energy. Missing, negative, or non-finite readings break
continuity, so integration never bridges a telemetry gap.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeGuard, TypeVar

Timestamp = TypeVar("Timestamp")


@dataclass(frozen=True, slots=True)
class EnergyIntegration:
    """Consumed energy and the duration covered by valid power intervals."""

    energy_wh: float
    observed_duration_seconds: float


def integrate_power_samples(
    samples: Iterable[tuple[float, float | None]],
) -> EnergyIntegration:
    """Integrate optional watt readings sampled at elapsed numeric seconds."""
    return _integrate_power_samples(samples, _numeric_elapsed_seconds)


def integrate_datetime_power_samples(
    samples: Iterable[tuple[datetime, float | None]],
) -> EnergyIntegration:
    """Integrate optional watt readings sampled at datetime timestamps."""
    return _integrate_power_samples(samples, _datetime_elapsed_seconds)


def _integrate_power_samples(
    samples: Iterable[tuple[Timestamp, float | None]],
    elapsed_seconds: Callable[[Timestamp, Timestamp], float],
) -> EnergyIntegration:
    energy_wh = 0.0
    observed_duration_seconds = 0.0
    previous: tuple[Timestamp, float | None] | None = None

    for timestamp, watts in samples:
        if previous is not None:
            previous_timestamp, previous_watts = previous
            duration = elapsed_seconds(timestamp, previous_timestamp)
            if (
                duration > 0.0
                and math.isfinite(duration)
                and _is_usable_power(previous_watts)
                and _is_usable_power(watts)
            ):
                energy_wh += ((previous_watts + watts) / 2.0) * duration / 3600.0
                observed_duration_seconds += duration
        previous = timestamp, watts

    return EnergyIntegration(
        energy_wh=energy_wh,
        observed_duration_seconds=observed_duration_seconds,
    )


def _is_usable_power(watts: float | None) -> TypeGuard[float]:
    """Return whether wattage represents finite, non-negative consumption."""
    return watts is not None and math.isfinite(watts) and watts >= 0.0


def _numeric_elapsed_seconds(current: float, previous: float) -> float:
    return current - previous


def _datetime_elapsed_seconds(current: datetime, previous: datetime) -> float:
    return (current - previous).total_seconds()
