from __future__ import annotations

import math
import os
import platform
from pathlib import Path
from typing import Any

import psutil

from systempulse.config import AppConfig
from systempulse.models import CollectionDiagnostic, CoreMetrics, DiagnosticKind
from systempulse.network import get_network_totals


def _get_disk_root() -> str:
    """Return the filesystem root used for system disk metrics."""
    if platform.system() == "Windows":
        system_drive = os.environ.get("SystemDrive")
        if system_drive:
            return system_drive.rstrip("/\\") + "\\"

        anchor = Path.cwd().anchor
        return anchor or "C:\\"

    return "/"


def _diagnostic(kind: DiagnosticKind, message: str) -> CollectionDiagnostic:
    return CollectionDiagnostic(collector="cpu_temperature", kind=kind, message=message)


def _temperature_value(reading: Any) -> float:
    value = float(reading.current)
    if not math.isfinite(value):
        raise ValueError("temperature is not finite")
    return value


def _collect_cpu_temperature(
    config: AppConfig,
) -> tuple[float | None, tuple[CollectionDiagnostic, ...]]:
    try:
        sensors = psutil.sensors_temperatures()
    except (AttributeError, NotImplementedError):
        return None, (
            _diagnostic(
                DiagnosticKind.UNAVAILABLE,
                "CPU temperature sensors are not supported on this platform.",
            ),
        )
    except OSError as error:
        return None, (
            _diagnostic(
                DiagnosticKind.EXECUTION_FAILED,
                f"CPU temperature sensors could not be read: {error}",
            ),
        )

    if not sensors:
        return None, (
            _diagnostic(DiagnosticKind.UNAVAILABLE, "No CPU temperature sensors were reported."),
        )

    selected_reading = None
    for sensor_name in config.temperature.preferred_sensors:
        readings = sensors.get(sensor_name)
        if readings:
            selected_reading = readings[0]
            break

    if selected_reading is None:
        for readings in sensors.values():
            for reading in readings:
                label = (getattr(reading, "label", "") or "").lower()
                if "package" in label or "tctl" in label or "cpu" in label:
                    selected_reading = reading
                    break
            if selected_reading is not None:
                break

    if selected_reading is None:
        return None, (
            _diagnostic(
                DiagnosticKind.UNAVAILABLE,
                "No reading could be identified as a CPU temperature.",
            ),
        )

    try:
        return _temperature_value(selected_reading), ()
    except (AttributeError, TypeError, ValueError) as error:
        return None, (
            _diagnostic(
                DiagnosticKind.MALFORMED_RESULT,
                f"CPU temperature sensor returned an invalid value: {error}",
            ),
        )


def _get_cpu_temperature(config: AppConfig) -> float | None:
    """Return only the temperature value for compatibility with the v1 helper."""
    temperature, _ = _collect_cpu_temperature(config)
    return temperature


def collect_core_metrics(config: AppConfig) -> CoreMetrics:
    """Collect one set of non-GPU metrics without assigning clocks or network rates."""
    cpu_usage = psutil.cpu_percent(interval=config.monitor.cpu_sample_interval)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(_get_disk_root())
    temperature, diagnostics = _collect_cpu_temperature(config)
    network = get_network_totals()

    return CoreMetrics(
        cpu_usage_percent=float(cpu_usage),
        ram_usage_percent=float(memory.percent),
        ram_used_bytes=int(memory.used),
        ram_total_bytes=int(memory.total),
        disk_usage_percent=float(disk.percent),
        disk_used_bytes=int(disk.used),
        disk_total_bytes=int(disk.total),
        cpu_temperature_celsius=temperature,
        network=network,
        diagnostics=diagnostics,
    )
