from __future__ import annotations

import csv
from pathlib import Path

from systempulse.models import NetworkSpeed, SystemSnapshot

CSV_HEADER = [
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


def save_snapshot(
    snapshot: SystemSnapshot,
    network_speed: NetworkSpeed,
    csv_path: str | Path,
) -> Path:
    path = Path(csv_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    gpu = snapshot.gpus[0] if snapshot.gpus else None

    row = [
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
        round(network_speed.upload_bytes_per_second, 2),
        round(network_speed.download_bytes_per_second, 2),
        gpu.name if gpu else "Unavailable",
        gpu.usage_percent if gpu else "Unavailable",
        gpu.temperature_celsius if gpu else "Unavailable",
        gpu.vram_used_mib if gpu else "Unavailable",
        gpu.vram_total_mib if gpu else "Unavailable",
        gpu.power_watts if gpu and gpu.power_watts is not None else "Unavailable",
    ]

    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if write_header:
            writer.writerow(CSV_HEADER)
        writer.writerow(row)

    return path
