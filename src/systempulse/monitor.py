from __future__ import annotations

import math
import time
from collections.abc import Callable

from rich.live import Live

from systempulse.service import MonitorService
from systempulse.ui import build_snapshot_view


def live_monitor(
    service: MonitorService,
    *,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> None:
    """Render on monotonic ticks, skipping missed ticks after slow collections."""
    clock = monotonic or time.monotonic
    sleeper = sleep or time.sleep
    refresh_interval = max(service.config.monitor.refresh_interval, 0.2)

    try:
        initial_snapshot = service.sample()
        next_tick = clock() + refresh_interval
        with Live(
            build_snapshot_view(initial_snapshot, service.config, show_network_speed=True),
            refresh_per_second=4,
            screen=True,
        ) as live:
            while True:
                delay = next_tick - clock()
                if delay > 0:
                    sleeper(delay)

                current_snapshot = service.sample()
                live.update(
                    build_snapshot_view(
                        current_snapshot,
                        service.config,
                        show_network_speed=True,
                    )
                )

                next_tick += refresh_interval
                current_time = clock()
                if next_tick <= current_time:
                    missed_ticks = math.floor((current_time - next_tick) / refresh_interval) + 1
                    next_tick += missed_ticks * refresh_interval
    except KeyboardInterrupt:
        return
