from __future__ import annotations

import math
import time
from collections.abc import Callable

from rich.live import Live

from systempulse.alerts import AlertEngine
from systempulse.history import HistoryError, HistoryStore
from systempulse.models import AlertEvent, SystemSnapshot
from systempulse.service import MonitorService
from systempulse.ui import build_snapshot_view


def live_monitor(
    service: MonitorService,
    *,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    alert_engine: AlertEngine | None = None,
    history_store: HistoryStore | None = None,
    history_warning: str | None = None,
) -> None:
    """Render on monotonic ticks, skipping missed ticks after slow collections."""
    clock = monotonic or time.monotonic
    sleeper = sleep or time.sleep
    refresh_interval = max(service.config.monitor.refresh_interval, 0.2)
    engine = alert_engine if alert_engine is not None else AlertEngine(service.config.alerts)

    try:
        initial_snapshot = service.sample()
        initial_events = engine.evaluate(initial_snapshot)
        history_store, history_warning = _persist_history(
            history_store,
            initial_snapshot,
            initial_events,
            history_warning,
        )
        next_tick = clock() + refresh_interval
        with Live(
            build_snapshot_view(
                initial_snapshot,
                service.config,
                show_network_speed=True,
                active_alerts=engine.active_alerts,
                history_warning=history_warning,
            ),
            refresh_per_second=4,
            screen=True,
        ) as live:
            while True:
                delay = next_tick - clock()
                if delay > 0:
                    sleeper(delay)

                current_snapshot = service.sample()
                current_events = engine.evaluate(current_snapshot)
                history_store, history_warning = _persist_history(
                    history_store,
                    current_snapshot,
                    current_events,
                    history_warning,
                )
                live.update(
                    build_snapshot_view(
                        current_snapshot,
                        service.config,
                        show_network_speed=True,
                        active_alerts=engine.active_alerts,
                        history_warning=history_warning,
                    )
                )

                next_tick += refresh_interval
                current_time = clock()
                if next_tick <= current_time:
                    missed_ticks = math.floor((current_time - next_tick) / refresh_interval) + 1
                    next_tick += missed_ticks * refresh_interval
    except KeyboardInterrupt:
        return


def _persist_history(
    store: HistoryStore | None,
    snapshot: SystemSnapshot,
    events: tuple[AlertEvent, ...],
    warning: str | None,
) -> tuple[HistoryStore | None, str | None]:
    if store is None:
        return None, warning
    try:
        store.record_sample(snapshot, events)
    except HistoryError as error:
        return None, str(error)
    return store, warning
