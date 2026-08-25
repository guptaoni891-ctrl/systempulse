from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

import systempulse.network as network
from systempulse.models import NetworkStats
from systempulse.network import calculate_network_speed, get_network_totals, measure_network_speed


def test_calculate_network_speed():
    first = NetworkStats(bytes_sent=1000, bytes_received=2000)
    second = NetworkStats(bytes_sent=3000, bytes_received=7000)

    result = calculate_network_speed(first, second, 2)

    assert result.upload_bytes_per_second == 1000
    assert result.download_bytes_per_second == 2500


def test_network_speed_rejects_zero_elapsed_time():
    counters = NetworkStats(bytes_sent=1000, bytes_received=2000)
    with pytest.raises(ValueError):
        calculate_network_speed(counters, counters, 0)


def test_get_network_totals_uses_wrapped_system_counters(monkeypatch):
    counters = SimpleNamespace(bytes_sent=1_000, bytes_recv=2_000)
    net_io_counters = Mock(return_value=counters)
    monkeypatch.setattr(network.psutil, "net_io_counters", net_io_counters)

    assert get_network_totals() == NetworkStats(1_000, 2_000)
    net_io_counters.assert_called_once_with(pernic=False, nowrap=True)


@pytest.mark.parametrize(("interval", "expected_sleep"), [(2.0, 2.0), (0.0, 0.1)])
def test_measure_network_speed_uses_actual_monotonic_elapsed_time(
    monkeypatch, interval, expected_sleep
):
    totals = Mock(
        side_effect=[
            NetworkStats(bytes_sent=1_000, bytes_received=2_000),
            NetworkStats(bytes_sent=3_000, bytes_received=7_000),
        ]
    )
    monotonic = Mock(side_effect=[10.0, 12.0])
    sleep = Mock()
    monkeypatch.setattr(network, "get_network_totals", totals)
    monkeypatch.setattr(network.time, "monotonic", monotonic)
    monkeypatch.setattr(network.time, "sleep", sleep)

    result = measure_network_speed(interval)

    assert result.upload_bytes_per_second == 1_000
    assert result.download_bytes_per_second == 2_500
    assert totals.call_count == 2
    assert monotonic.mock_calls == [call(), call()]
    sleep.assert_called_once_with(expected_sleep)
