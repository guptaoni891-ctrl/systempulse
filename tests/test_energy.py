from datetime import UTC, datetime, timedelta

import pytest

from systempulse.energy import (
    EnergyIntegration,
    PowerEnergyAccumulator,
    integrate_datetime_power_samples,
    integrate_power_samples,
)


@pytest.mark.parametrize(
    "samples",
    [
        (),
        ((0.0, 100.0),),
    ],
)
def test_fewer_than_two_samples_produce_no_energy_or_observed_duration(samples):
    assert integrate_power_samples(samples) == EnergyIntegration(0.0, 0.0)


def test_running_accumulator_exposes_incremental_energy_and_duration():
    accumulator = PowerEnergyAccumulator()

    assert accumulator.energy_wh == 0.0
    assert accumulator.observed_duration_seconds == 0.0
    accumulator.observe(0.0, 100.0)
    accumulator.observe(1800.0, 200.0)
    accumulator.observe(5400.0, 50.0)

    assert accumulator.energy_wh == 200.0
    assert accumulator.observed_duration_seconds == 5400.0
    assert accumulator.result == EnergyIntegration(200.0, 5400.0)


def test_constant_load_uses_elapsed_time():
    result = integrate_power_samples(((0.0, 100.0), (3600.0, 100.0)))

    assert result.energy_wh == 100.0
    assert result.observed_duration_seconds == 3600.0


def test_changing_load_uses_trapezoidal_integration():
    result = integrate_power_samples(((0.0, 100.0), (3600.0, 200.0)))

    assert result.energy_wh == 150.0
    assert result.observed_duration_seconds == 3600.0


def test_irregular_intervals_are_integrated_independently():
    result = integrate_power_samples(
        (
            (0.0, 100.0),
            (1800.0, 200.0),
            (5400.0, 50.0),
        )
    )

    assert result.energy_wh == 200.0
    assert result.observed_duration_seconds == 5400.0


def test_missing_middle_sample_breaks_continuity():
    result = integrate_power_samples(
        (
            (0.0, 100.0),
            (1800.0, None),
            (3600.0, 100.0),
        )
    )

    assert result == EnergyIntegration(0.0, 0.0)


def test_integration_resumes_between_consecutive_valid_samples_after_gap():
    result = integrate_power_samples(
        (
            (0.0, 100.0),
            (1800.0, None),
            (3600.0, 100.0),
            (7200.0, 100.0),
        )
    )

    assert result == EnergyIntegration(100.0, 3600.0)


def test_separated_valid_intervals_are_summed_without_bridging_gap():
    result = integrate_power_samples(
        (
            (0.0, 100.0),
            (3600.0, 200.0),
            (7200.0, None),
            (10800.0, 50.0),
            (12600.0, 150.0),
        )
    )

    assert result == EnergyIntegration(200.0, 5400.0)


@pytest.mark.parametrize(
    "samples",
    [
        ((100.0, 100.0), (100.0, 200.0)),
        ((200.0, 100.0), (100.0, 200.0)),
    ],
)
def test_non_positive_time_intervals_are_ignored(samples):
    assert integrate_power_samples(samples) == EnergyIntegration(0.0, 0.0)


def test_negative_power_breaks_continuity_instead_of_reducing_consumption():
    result = integrate_power_samples(
        (
            (0.0, 100.0),
            (3600.0, -50.0),
            (7200.0, 100.0),
            (10800.0, 100.0),
        )
    )

    assert result == EnergyIntegration(100.0, 3600.0)


@pytest.mark.parametrize("invalid_power", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_power_breaks_continuity(invalid_power):
    result = integrate_power_samples(
        (
            (0.0, 100.0),
            (3600.0, invalid_power),
            (7200.0, 100.0),
        )
    )

    assert result == EnergyIntegration(0.0, 0.0)


def test_fractional_monotonic_timestamps_preserve_precision():
    result = integrate_power_samples(((10.25, 40.0), (12.75, 80.0)))

    assert result.energy_wh == pytest.approx(60.0 * 2.5 / 3600.0)
    assert result.observed_duration_seconds == 2.5


def test_utc_datetime_timestamps_are_supported():
    start = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)

    result = integrate_datetime_power_samples(
        (
            (start, 100.0),
            (start + timedelta(minutes=30), 200.0),
        )
    )

    assert result == EnergyIntegration(75.0, 1800.0)
