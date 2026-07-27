import pytest

from systempulse.models import NetworkStats
from systempulse.network import calculate_network_speed


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
