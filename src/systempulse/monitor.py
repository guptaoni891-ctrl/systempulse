from __future__ import annotations

import time
from typing import Any

from rich.live import Live

from systempulse.collector import collect_system_snapshot
from systempulse.models import NetworkSpeed
from systempulse.network import calculate_network_speed
from systempulse.ui import build_snapshot_view


def live_monitor(config: dict[str, Any], *, include_gpu: bool = True) -> None:
    refresh_interval = max(float(config["monitor"]["refresh_interval"]), 0.2)
    previous_snapshot = collect_system_snapshot(config, include_gpu=include_gpu)
    previous_time = time.monotonic()
    initial_speed = NetworkSpeed(0.0, 0.0)

    with Live(
        build_snapshot_view(previous_snapshot, config, initial_speed),
        refresh_per_second=4,
        screen=True,
    ) as live:
        try:
            while True:
                time.sleep(refresh_interval)
                current_snapshot = collect_system_snapshot(config, include_gpu=include_gpu)
                current_time = time.monotonic()
                speed = calculate_network_speed(
                    previous_snapshot.network,
                    current_snapshot.network,
                    current_time - previous_time,
                )
                live.update(build_snapshot_view(current_snapshot, config, speed))
                previous_snapshot = current_snapshot
                previous_time = current_time
        except KeyboardInterrupt:
            return
