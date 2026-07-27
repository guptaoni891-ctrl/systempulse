from __future__ import annotations

import time

import psutil

from systempulse.models import NetworkSpeed, NetworkStats


def get_network_totals() -> NetworkStats:
    counters = psutil.net_io_counters(pernic=False, nowrap=True)
    return NetworkStats(
        bytes_sent=int(counters.bytes_sent),
        bytes_received=int(counters.bytes_recv),
    )


def calculate_network_speed(
    previous: NetworkStats,
    current: NetworkStats,
    elapsed_seconds: float,
) -> NetworkSpeed:
    if elapsed_seconds <= 0:
        raise ValueError("elapsed_seconds must be greater than zero.")

    uploaded = max(0, current.bytes_sent - previous.bytes_sent)
    downloaded = max(0, current.bytes_received - previous.bytes_received)

    return NetworkSpeed(
        upload_bytes_per_second=uploaded / elapsed_seconds,
        download_bytes_per_second=downloaded / elapsed_seconds,
    )


def measure_network_speed(interval: float = 1.0) -> NetworkSpeed:
    interval = max(float(interval), 0.1)
    first = get_network_totals()
    started = time.monotonic()
    time.sleep(interval)
    second = get_network_totals()
    elapsed = time.monotonic() - started
    return calculate_network_speed(first, second, elapsed)
