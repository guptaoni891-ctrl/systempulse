from __future__ import annotations

import os
import platform
from datetime import datetime
from pathlib import Path

import psutil

from systempulse.config import AppConfig
from systempulse.gpu import get_gpu_stats
from systempulse.models import NetworkStats, SystemSnapshot


def _get_disk_root() -> str:
    """Return the filesystem root used for system disk metrics."""
    if platform.system() == "Windows":
        system_drive = os.environ.get("SystemDrive")
        if system_drive:
            return system_drive.rstrip("/\\") + "\\"

        anchor = Path.cwd().anchor
        return anchor or "C:\\"

    return "/"


def _get_cpu_temperature(config: AppConfig) -> float | None:
    """Return a CPU temperature when psutil exposes one on this platform."""
    try:
        sensors = psutil.sensors_temperatures()
    except (AttributeError, NotImplementedError, OSError):
        return None

    if not sensors:
        return None

    preferred = config.temperature.preferred_sensors
    for sensor_name in preferred:
        readings = sensors.get(sensor_name)
        if readings:
            return float(readings[0].current)

    for readings in sensors.values():
        for reading in readings:
            label = (reading.label or "").lower()
            if "package" in label or "tctl" in label or "cpu" in label:
                return float(reading.current)

    return None


def collect_system_snapshot(
    config: AppConfig,
    *,
    include_gpu: bool = True,
) -> SystemSnapshot:
    cpu_interval = config.monitor.cpu_sample_interval
    cpu_usage = psutil.cpu_percent(interval=max(cpu_interval, 0.0))
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(_get_disk_root())
    network = psutil.net_io_counters(pernic=False, nowrap=True)

    return SystemSnapshot(
        timestamp=datetime.now().replace(microsecond=0),
        cpu_usage_percent=float(cpu_usage),
        ram_usage_percent=float(memory.percent),
        ram_used_bytes=int(memory.used),
        ram_total_bytes=int(memory.total),
        disk_usage_percent=float(disk.percent),
        disk_used_bytes=int(disk.used),
        disk_total_bytes=int(disk.total),
        cpu_temperature_celsius=_get_cpu_temperature(config),
        network=NetworkStats(
            bytes_sent=int(network.bytes_sent),
            bytes_received=int(network.bytes_recv),
        ),
        gpus=get_gpu_stats() if include_gpu else (),
    )
