from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from systempulse.models import NetworkSpeed, ProcessStats, SystemSnapshot
from systempulse.status import classify, classify_temperature
from systempulse.utils import format_bytes, format_rate

console = Console()


def _status_text(label: str) -> Text:
    styles = {
        "Normal": "green",
        "High": "yellow",
        "Hot": "yellow",
        "Critical": "bold red",
    }
    return Text(label, style=styles.get(label, "white"))


def build_snapshot_view(
    snapshot: SystemSnapshot,
    config: dict[str, Any],
    network_speed: NetworkSpeed | None = None,
) -> Group:
    thresholds = config["thresholds"]
    table = Table(title=f"SystemPulse — {snapshot.timestamp}", expand=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_column("Status")

    cpu_status = classify(
        snapshot.cpu_usage_percent,
        thresholds["cpu_warning"],
        thresholds["cpu_critical"],
    )
    ram_status = classify(
        snapshot.ram_usage_percent,
        thresholds["memory_warning"],
        thresholds["memory_critical"],
    )
    disk_status = classify(
        snapshot.disk_usage_percent,
        thresholds["disk_warning"],
        thresholds["disk_critical"],
    )

    table.add_row("CPU", f"{snapshot.cpu_usage_percent:.1f}%", _status_text(cpu_status))
    table.add_row(
        "RAM",
        f"{format_bytes(snapshot.ram_used_bytes)} / {format_bytes(snapshot.ram_total_bytes)} "
        f"({snapshot.ram_usage_percent:.1f}%)",
        _status_text(ram_status),
    )
    table.add_row(
        "Disk /",
        f"{format_bytes(snapshot.disk_used_bytes)} / {format_bytes(snapshot.disk_total_bytes)} "
        f"({snapshot.disk_usage_percent:.1f}%)",
        _status_text(disk_status),
    )

    if snapshot.cpu_temperature_celsius is None:
        table.add_row("CPU temperature", "Unavailable", "—")
    else:
        temperature_status = classify_temperature(
            snapshot.cpu_temperature_celsius,
            thresholds["temperature_warning"],
            thresholds["temperature_critical"],
        )
        table.add_row(
            "CPU temperature",
            f"{snapshot.cpu_temperature_celsius:.1f}°C",
            _status_text(temperature_status),
        )

    table.add_row("Network sent", format_bytes(snapshot.network.bytes_sent), "Since boot")
    table.add_row("Network received", format_bytes(snapshot.network.bytes_received), "Since boot")

    if network_speed is not None:
        table.add_row("Upload", format_rate(network_speed.upload_bytes_per_second), "Live")
        table.add_row("Download", format_rate(network_speed.download_bytes_per_second), "Live")

    gpu_table = Table(title="GPU", expand=True)
    gpu_table.add_column("GPU")
    gpu_table.add_column("Usage")
    gpu_table.add_column("Temperature")
    gpu_table.add_column("VRAM")
    gpu_table.add_column("Power")
    gpu_table.add_column("Status")

    if not snapshot.gpus:
        gpu_table.add_row("NVIDIA GPU unavailable", "—", "—", "—", "—", "—")
    else:
        for gpu in snapshot.gpus:
            gpu_status = classify(
                gpu.usage_percent,
                thresholds["gpu_warning"],
                thresholds["gpu_critical"],
            )
            gpu_table.add_row(
                gpu.name,
                f"{gpu.usage_percent:.1f}%",
                f"{gpu.temperature_celsius:.1f}°C",
                f"{gpu.vram_used_mib:.0f} / {gpu.vram_total_mib:.0f} MiB",
                f"{gpu.power_watts:.2f} W" if gpu.power_watts is not None else "Unavailable",
                _status_text(gpu_status),
            )

    return Group(table, gpu_table)


def print_snapshot(
    snapshot: SystemSnapshot,
    config: dict[str, Any],
    network_speed: NetworkSpeed | None = None,
) -> None:
    console.print(build_snapshot_view(snapshot, config, network_speed))


def print_processes(processes: list[ProcessStats]) -> None:
    table = Table(title="Top CPU Processes", expand=True)
    table.add_column("PID", justify="right")
    table.add_column("Process")
    table.add_column("CPU", justify="right")
    table.add_column("Memory", justify="right")

    for process in processes:
        table.add_row(
            str(process.pid),
            process.name,
            f"{process.cpu_percent:.1f}%",
            f"{process.memory_percent:.1f}%",
        )

    console.print(table)


def print_warning(message: str) -> None:
    console.print(Panel(message, title="Configuration warning", style="yellow"))
