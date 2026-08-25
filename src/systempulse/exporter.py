from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from systempulse.models import SystemSnapshot
from systempulse.service import MonitorService

LOGGER = logging.getLogger(__name__)


class ExporterError(RuntimeError):
    """Raised when the Prometheus exporter cannot start or operate."""


class PrometheusDependencyError(ExporterError):
    """Raised when the optional Prometheus client is unavailable."""


def _load_prometheus() -> tuple[Any, Any, Any, Any]:
    try:
        from prometheus_client import CollectorRegistry, start_http_server
        from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
    except ImportError as error:
        raise PrometheusDependencyError(
            'Prometheus support is not installed. Install it with '
            '`pip install "systempulse[prometheus]"`.'
        ) from error
    return CollectorRegistry, start_http_server, CounterMetricFamily, GaugeMetricFamily


@dataclass(frozen=True, slots=True)
class ExporterStateView:
    snapshot: SystemSnapshot | None
    up: bool
    sampling_errors: int
    successful_sample_monotonic: float | None


class ExporterState:
    """Thread-safe, atomically replaced exporter state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: SystemSnapshot | None = None
        self._up = False
        self._sampling_errors = 0
        self._successful_sample_monotonic: float | None = None

    def record_success(self, snapshot: SystemSnapshot, sampled_monotonic: float) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._up = True
            self._successful_sample_monotonic = sampled_monotonic

    def record_failure(self) -> None:
        with self._lock:
            self._up = False
            self._sampling_errors += 1

    def read(self) -> ExporterStateView:
        with self._lock:
            return ExporterStateView(
                snapshot=self._snapshot,
                up=self._up,
                sampling_errors=self._sampling_errors,
                successful_sample_monotonic=self._successful_sample_monotonic,
            )


def _ratio(percent: float) -> float:
    return min(1.0, max(0.0, float(percent) / 100.0))


class SystemPulseCollector:
    """Emit metrics from in-memory state without collecting system data."""

    def __init__(
        self,
        state: ExporterState,
        *,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._state = state
        self._monotonic = monotonic or time.monotonic

    def collect(self) -> Iterator[Any]:
        _, _, CounterMetricFamily, GaugeMetricFamily = _load_prometheus()
        state = self._state.read()

        up = GaugeMetricFamily(
            "systempulse_up",
            "Whether the latest SystemPulse sampling attempt succeeded.",
        )
        up.add_metric([], 1 if state.up else 0)
        yield up

        errors = CounterMetricFamily(
            "systempulse_sampling_errors_total",
            "Total failed SystemPulse sampling attempts.",
        )
        errors.add_metric([], state.sampling_errors)
        yield errors

        snapshot = state.snapshot
        if snapshot is None or state.successful_sample_monotonic is None:
            return

        yield _gauge(
            GaugeMetricFamily,
            "systempulse_last_sample_timestamp_seconds",
            "Unix timestamp of the latest successful SystemPulse sample.",
            snapshot.timestamp.timestamp(),
        )
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_sample_age_seconds",
            "Monotonic age of the latest successful SystemPulse sample.",
            max(0.0, self._monotonic() - state.successful_sample_monotonic),
        )
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_cpu_usage_ratio",
            "Current CPU usage as a ratio from 0 to 1.",
            _ratio(snapshot.cpu_usage_percent),
        )
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_memory_usage_ratio",
            "Current memory usage as a ratio from 0 to 1.",
            _ratio(snapshot.ram_usage_percent),
        )
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_memory_used_bytes",
            "Current used memory in bytes.",
            snapshot.ram_used_bytes,
        )
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_memory_total_bytes",
            "Total memory in bytes.",
            snapshot.ram_total_bytes,
        )
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_disk_usage_ratio",
            "Current system disk usage as a ratio from 0 to 1.",
            _ratio(snapshot.disk_usage_percent),
        )
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_disk_used_bytes",
            "Current used system disk space in bytes.",
            snapshot.disk_used_bytes,
        )
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_disk_total_bytes",
            "Total system disk space in bytes.",
            snapshot.disk_total_bytes,
        )
        if snapshot.cpu_temperature_celsius is not None:
            yield _gauge(
                GaugeMetricFamily,
                "systempulse_cpu_temperature_celsius",
                "Current CPU temperature in degrees Celsius.",
                snapshot.cpu_temperature_celsius,
            )

        sent = CounterMetricFamily(
            "systempulse_network_bytes_sent_total",
            "Cumulative bytes sent since the operating system counter was reset.",
        )
        sent.add_metric([], snapshot.network.bytes_sent)
        yield sent
        received = CounterMetricFamily(
            "systempulse_network_bytes_received_total",
            "Cumulative bytes received since the operating system counter was reset.",
        )
        received.add_metric([], snapshot.network.bytes_received)
        yield received
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_network_upload_bytes_per_second",
            "Current network upload rate in bytes per second.",
            snapshot.network_speed.upload_bytes_per_second,
        )
        yield _gauge(
            GaugeMetricFamily,
            "systempulse_network_download_bytes_per_second",
            "Current network download rate in bytes per second.",
            snapshot.network_speed.download_bytes_per_second,
        )

        if not snapshot.gpus:
            return

        gpu_metrics = (
            ("systempulse_gpu_usage_ratio", "Current GPU usage as a ratio from 0 to 1."),
            (
                "systempulse_gpu_temperature_celsius",
                "Current GPU temperature in degrees Celsius.",
            ),
            ("systempulse_gpu_memory_used_bytes", "Current used GPU memory in bytes."),
            ("systempulse_gpu_memory_total_bytes", "Total GPU memory in bytes."),
            ("systempulse_gpu_power_watts", "Current GPU power usage in watts."),
        )
        families = {
            name: GaugeMetricFamily(name, help_text, labels=["gpu"])
            for name, help_text in gpu_metrics
        }
        for index, gpu in enumerate(snapshot.gpus):
            label = [str(index)]
            families["systempulse_gpu_usage_ratio"].add_metric(
                label, _ratio(gpu.usage_percent)
            )
            families["systempulse_gpu_temperature_celsius"].add_metric(
                label, gpu.temperature_celsius
            )
            families["systempulse_gpu_memory_used_bytes"].add_metric(
                label, gpu.vram_used_mib * 1024 * 1024
            )
            families["systempulse_gpu_memory_total_bytes"].add_metric(
                label, gpu.vram_total_mib * 1024 * 1024
            )
            if gpu.power_watts is not None:
                families["systempulse_gpu_power_watts"].add_metric(label, gpu.power_watts)
        yield from families.values()


def _gauge(metric_family: Any, name: str, help_text: str, value: float) -> Any:
    metric = metric_family(name, help_text)
    metric.add_metric([], value)
    return metric


def create_registry(
    state: ExporterState,
    *,
    monotonic: Callable[[], float] | None = None,
) -> Any:
    CollectorRegistry, _, _, _ = _load_prometheus()
    registry = CollectorRegistry()
    registry.register(SystemPulseCollector(state, monotonic=monotonic))
    return registry


def run_sampling_loop(
    service: MonitorService,
    state: ExporterState,
    interval: float,
    stop_event: threading.Event,
    *,
    monotonic: Callable[[], float] | None = None,
) -> None:
    """Sample immediately, then on anchored monotonic ticks until stopped."""
    clock = monotonic or time.monotonic
    next_tick = clock()
    while not stop_event.is_set():
        try:
            snapshot = service.sample()
        except Exception as error:  # Sampling failures are recoverable exporter state.
            state.record_failure()
            LOGGER.warning("SystemPulse sampling failed: %s", error)
        else:
            state.record_success(snapshot, clock())

        next_tick += interval
        current_time = clock()
        if next_tick <= current_time:
            missed_ticks = math.floor((current_time - next_tick) / interval) + 1
            next_tick += missed_ticks * interval
        if stop_event.wait(max(0.0, next_tick - current_time)):
            return


def serve_exporter(
    service: MonitorService,
    *,
    host: str,
    port: int,
    interval: float,
    monotonic: Callable[[], float] | None = None,
) -> None:
    """Serve the latest sample until interrupted, then release all server resources."""
    _, start_http_server, _, _ = _load_prometheus()
    state = ExporterState()
    registry = create_registry(state, monotonic=monotonic)
    try:
        http_server, server_thread = start_http_server(port, addr=host, registry=registry)
    except OSError as error:
        raise ExporterError(f"Could not listen on {host}:{port}: {error}") from error

    stop_event = threading.Event()
    sampling_thread = threading.Thread(
        target=run_sampling_loop,
        args=(service, state, interval, stop_event),
        kwargs={"monotonic": monotonic},
        name="systempulse-sampler",
    )
    sampling_thread.start()
    try:
        _wait_for_sampling_thread(sampling_thread)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        sampling_thread.join()
        http_server.shutdown()
        http_server.server_close()
        if server_thread.is_alive():
            server_thread.join(timeout=2.0)


def _wait_for_sampling_thread(sampling_thread: threading.Thread) -> None:
    while sampling_thread.is_alive():
        sampling_thread.join(timeout=0.5)
