from __future__ import annotations

import csv
from pathlib import Path

from systempulse.models import SystemSnapshot

LEGACY_CSV_HEADER = [
    "timestamp",
    "cpu_usage_percent",
    "ram_usage_percent",
    "ram_used_bytes",
    "ram_total_bytes",
    "disk_usage_percent",
    "disk_used_bytes",
    "disk_total_bytes",
    "cpu_temperature_celsius",
    "network_bytes_sent",
    "network_bytes_received",
    "upload_bytes_per_second",
    "download_bytes_per_second",
    "gpu_name",
    "gpu_usage_percent",
    "gpu_temperature_celsius",
    "gpu_vram_used_mib",
    "gpu_vram_total_mib",
    "gpu_power_watts",
]
POWER_CSV_HEADER = [
    "cpu_package_watts",
    "gpu_total_watts",
    "cpu_gpu_watts",
    "estimated_system_watts",
    "estimated_wall_watts",
    "actual_wall_watts",
    "cpu_power_source",
]
CSV_HEADER = LEGACY_CSV_HEADER + POWER_CSV_HEADER


def save_snapshot(
    snapshot: SystemSnapshot,
    csv_path: str | Path,
) -> Path:
    path = Path(csv_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    header = CSV_HEADER if write_header else _existing_header(path)
    if header not in (LEGACY_CSV_HEADER, CSV_HEADER):
        raise ValueError(
            f"Existing CSV file {path} has an incompatible header; "
            "expected the SystemPulse legacy or current header."
        )
    gpu = snapshot.gpus[0] if snapshot.gpus else None

    legacy_row = [
        snapshot.timestamp.isoformat(sep=" "),
        snapshot.cpu_usage_percent,
        snapshot.ram_usage_percent,
        snapshot.ram_used_bytes,
        snapshot.ram_total_bytes,
        snapshot.disk_usage_percent,
        snapshot.disk_used_bytes,
        snapshot.disk_total_bytes,
        (
            snapshot.cpu_temperature_celsius
            if snapshot.cpu_temperature_celsius is not None
            else "Unavailable"
        ),
        snapshot.network.bytes_sent,
        snapshot.network.bytes_received,
        round(snapshot.network_speed.upload_bytes_per_second, 2),
        round(snapshot.network_speed.download_bytes_per_second, 2),
        gpu.name if gpu else "Unavailable",
        gpu.usage_percent if gpu else "Unavailable",
        gpu.temperature_celsius if gpu else "Unavailable",
        gpu.vram_used_mib if gpu else "Unavailable",
        gpu.vram_total_mib if gpu else "Unavailable",
        gpu.power_watts if gpu and gpu.power_watts is not None else "Unavailable",
    ]
    power = snapshot.power
    power_row = [
        power.cpu_package_watts if power.cpu_package_watts is not None else "Unavailable",
        power.gpu_total_watts if power.gpu_total_watts is not None else "Unavailable",
        power.cpu_gpu_watts if power.cpu_gpu_watts is not None else "Unavailable",
        (
            power.estimated_system_watts
            if power.estimated_system_watts is not None
            else "Unavailable"
        ),
        (power.estimated_wall_watts if power.estimated_wall_watts is not None else "Unavailable"),
        power.actual_wall_watts if power.actual_wall_watts is not None else "Unavailable",
        power.cpu_source if power.cpu_source is not None else "Unavailable",
    ]
    row = legacy_row + power_row if header == CSV_HEADER else legacy_row

    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if write_header:
            writer.writerow(CSV_HEADER)
        writer.writerow(row)

    return path


def _existing_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as file:
        return next(csv.reader(file), [])
