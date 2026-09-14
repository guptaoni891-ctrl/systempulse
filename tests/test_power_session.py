from datetime import UTC, datetime

import pytest

from systempulse.models import NetworkSpeed, NetworkStats, PowerStats, SystemSnapshot
from systempulse.power_session import PowerSessionTracker


def _snapshot(power: PowerStats) -> SystemSnapshot:
    return SystemSnapshot(
        timestamp=datetime(2026, 9, 12, 8, 0, tzinfo=UTC),
        cpu_usage_percent=10.0,
        ram_usage_percent=20.0,
        ram_used_bytes=2_000,
        ram_total_bytes=10_000,
        disk_usage_percent=30.0,
        disk_used_bytes=3_000,
        disk_total_bytes=10_000,
        cpu_temperature_celsius=None,
        network=NetworkStats(1_000, 2_000),
        network_speed=NetworkSpeed(100.0, 200.0),
        gpus=(),
        power=power,
    )


def _observe_wall_series(
    readings: tuple[tuple[float, float | None, float | None], ...],
):
    tracker = PowerSessionTracker()
    result = tracker.stats
    for timestamp, estimated, actual in readings:
        result = tracker.observe(
            _snapshot(
                PowerStats(
                    estimated_wall_watts=estimated,
                    actual_wall_watts=actual,
                )
            ),
            timestamp,
        )
    return result


def test_first_observation_populates_currents_and_peaks_without_energy():
    tracker = PowerSessionTracker()
    power = PowerStats(
        cpu_package_watts=31.2,
        gpu_total_watts=108.4,
        cpu_gpu_watts=139.6,
        estimated_system_watts=174.6,
        estimated_wall_watts=194.0,
        actual_wall_watts=188.0,
    )

    result = tracker.observe(_snapshot(power), 50.0)

    assert result.session_duration_seconds == 0.0
    assert result.current_cpu_package_watts == 31.2
    assert result.current_gpu_total_watts == 108.4
    assert result.current_cpu_gpu_watts == 139.6
    assert result.current_estimated_system_watts == 174.6
    assert result.current_estimated_wall_watts == 194.0
    assert result.current_actual_wall_watts == 188.0
    assert result.average_estimated_wall_watts is None
    assert result.peak_estimated_wall_watts == 194.0
    assert result.estimated_wall_energy_wh == 0.0
    assert result.estimated_wall_observed_duration_seconds == 0.0


def test_constant_estimated_wall_power_uses_actual_monotonic_elapsed_time():
    result = _observe_wall_series(((0.0, 100.0, None), (3600.0, 100.0, None)))

    assert result.session_duration_seconds == 3600.0
    assert result.average_estimated_wall_watts == 100.0
    assert result.peak_estimated_wall_watts == 100.0
    assert result.estimated_wall_energy_wh == 100.0
    assert result.estimated_wall_observed_duration_seconds == 3600.0


def test_estimated_wall_power_uses_trapezoidal_integration():
    result = _observe_wall_series(((0.0, 100.0, None), (3600.0, 200.0, None)))

    assert result.average_estimated_wall_watts == 150.0
    assert result.peak_estimated_wall_watts == 200.0
    assert result.estimated_wall_energy_wh == 150.0


def test_irregular_session_average_is_time_weighted():
    result = _observe_wall_series(((0.0, 100.0, None), (1800.0, 200.0, None), (5400.0, 50.0, None)))

    assert result.estimated_wall_energy_wh == 200.0
    assert result.estimated_wall_observed_duration_seconds == 5400.0
    assert result.average_estimated_wall_watts == pytest.approx(200.0 * 3600.0 / 5400.0)
    assert result.average_estimated_wall_watts != pytest.approx((100.0 + 200.0 + 50.0) / 3.0)


def test_session_duration_continues_across_estimated_telemetry_gap():
    result = _observe_wall_series(((0.0, 100.0, None), (1800.0, None, None), (3600.0, 100.0, None)))

    assert result.session_duration_seconds == 3600.0
    assert result.average_estimated_wall_watts is None
    assert result.estimated_wall_energy_wh == 0.0
    assert result.estimated_wall_observed_duration_seconds == 0.0


def test_session_integration_resumes_after_estimated_telemetry_gap():
    result = _observe_wall_series(
        (
            (0.0, 100.0, None),
            (1800.0, None, None),
            (3600.0, 100.0, None),
            (7200.0, 100.0, None),
        )
    )

    assert result.session_duration_seconds == 7200.0
    assert result.average_estimated_wall_watts == 100.0
    assert result.peak_estimated_wall_watts == 100.0
    assert result.estimated_wall_energy_wh == 100.0
    assert result.estimated_wall_observed_duration_seconds == 3600.0


def test_estimated_and_actual_wall_sessions_are_independent():
    result = _observe_wall_series(
        (
            (0.0, 100.0, None),
            (3600.0, 100.0, 50.0),
            (7200.0, 100.0, 150.0),
        )
    )

    assert result.average_estimated_wall_watts == 100.0
    assert result.peak_estimated_wall_watts == 100.0
    assert result.estimated_wall_energy_wh == 200.0
    assert result.estimated_wall_observed_duration_seconds == 7200.0
    assert result.average_actual_wall_watts == 100.0
    assert result.peak_actual_wall_watts == 150.0
    assert result.actual_wall_energy_wh == 100.0
    assert result.actual_wall_observed_duration_seconds == 3600.0


def test_missing_actual_wall_telemetry_remains_unavailable_not_zero():
    result = _observe_wall_series(((0.0, 100.0, None), (3600.0, 100.0, None)))

    assert result.current_actual_wall_watts is None
    assert result.average_actual_wall_watts is None
    assert result.peak_actual_wall_watts is None
    assert result.actual_wall_energy_wh == 0.0
    assert result.actual_wall_observed_duration_seconds == 0.0


@pytest.mark.parametrize("invalid", [-1.0, float("nan"), float("inf"), float("-inf")])
def test_invalid_watts_are_unavailable_and_break_continuity(invalid):
    tracker = PowerSessionTracker()
    tracker.observe(_snapshot(PowerStats(estimated_wall_watts=100.0)), 0.0)
    invalid_result = tracker.observe(
        _snapshot(
            PowerStats(
                cpu_package_watts=invalid,
                gpu_total_watts=invalid,
                cpu_gpu_watts=invalid,
                estimated_system_watts=invalid,
                estimated_wall_watts=invalid,
                actual_wall_watts=invalid,
            )
        ),
        3600.0,
    )
    result = tracker.observe(_snapshot(PowerStats(estimated_wall_watts=100.0)), 7200.0)

    assert invalid_result.current_cpu_package_watts is None
    assert invalid_result.current_gpu_total_watts is None
    assert invalid_result.current_cpu_gpu_watts is None
    assert invalid_result.current_estimated_system_watts is None
    assert invalid_result.current_estimated_wall_watts is None
    assert invalid_result.current_actual_wall_watts is None
    assert result.estimated_wall_energy_wh == 0.0
    assert result.estimated_wall_observed_duration_seconds == 0.0


def test_zero_watts_is_valid_for_current_average_peak_and_duration():
    result = _observe_wall_series(((0.0, 0.0, 0.0), (3600.0, 0.0, 0.0)))

    assert result.current_estimated_wall_watts == 0.0
    assert result.average_estimated_wall_watts == 0.0
    assert result.peak_estimated_wall_watts == 0.0
    assert result.estimated_wall_energy_wh == 0.0
    assert result.estimated_wall_observed_duration_seconds == 3600.0
    assert result.average_actual_wall_watts == 0.0
    assert result.peak_actual_wall_watts == 0.0


def test_duplicate_and_backwards_monotonic_values_never_reduce_duration_or_energy():
    tracker = PowerSessionTracker()
    tracker.observe(_snapshot(PowerStats(estimated_wall_watts=100.0)), 100.0)
    forward = tracker.observe(_snapshot(PowerStats(estimated_wall_watts=100.0)), 200.0)
    duplicate = tracker.observe(_snapshot(PowerStats(estimated_wall_watts=200.0)), 200.0)
    backwards = tracker.observe(_snapshot(PowerStats(estimated_wall_watts=300.0)), 150.0)

    assert forward.session_duration_seconds == 100.0
    assert duplicate.session_duration_seconds == 100.0
    assert backwards.session_duration_seconds == 100.0
    assert duplicate.estimated_wall_energy_wh == forward.estimated_wall_energy_wh
    assert backwards.estimated_wall_energy_wh == forward.estimated_wall_energy_wh


def test_current_component_values_always_mirror_latest_snapshot_power():
    tracker = PowerSessionTracker()
    tracker.observe(_snapshot(PowerStats(estimated_wall_watts=100.0)), 0.0)

    result = tracker.observe(
        _snapshot(
            PowerStats(
                cpu_package_watts=42.0,
                gpu_total_watts=120.0,
                cpu_gpu_watts=162.0,
                estimated_system_watts=197.0,
                estimated_wall_watts=219.0,
                actual_wall_watts=210.0,
            )
        ),
        10.0,
    )

    assert result.current_cpu_package_watts == 42.0
    assert result.current_gpu_total_watts == 120.0
    assert result.current_cpu_gpu_watts == 162.0
    assert result.current_estimated_system_watts == 197.0
    assert result.current_estimated_wall_watts == 219.0
    assert result.current_actual_wall_watts == 210.0
