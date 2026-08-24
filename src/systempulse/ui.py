from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from systempulse.config import AppConfig
from systempulse.models import ActiveAlert, AlertSeverity, ProcessStats, SystemSnapshot
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
    config: AppConfig,
    *,
    show_network_speed: bool = False,
    active_alerts: tuple[ActiveAlert, ...] | None = None,
) -> Group:
    thresholds = config.thresholds
    display_timestamp = snapshot.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    table = Table(title=f"SystemPulse — {display_timestamp}", expand=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_column("Status")

    cpu_status = classify(
        snapshot.cpu_usage_percent,
        thresholds.cpu.warning,
        thresholds.cpu.critical,
    )
    ram_status = classify(
        snapshot.ram_usage_percent,
        thresholds.memory.warning,
        thresholds.memory.critical,
    )
    disk_status = classify(
        snapshot.disk_usage_percent,
        thresholds.disk.warning,
        thresholds.disk.critical,
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
            thresholds.temperature.warning,
            thresholds.temperature.critical,
        )
        table.add_row(
            "CPU temperature",
            f"{snapshot.cpu_temperature_celsius:.1f}°C",
            _status_text(temperature_status),
        )

    table.add_row("Network sent", format_bytes(snapshot.network.bytes_sent), "Since boot")
    table.add_row("Network received", format_bytes(snapshot.network.bytes_received), "Since boot")

    if show_network_speed:
        table.add_row(
            "Upload",
            format_rate(snapshot.network_speed.upload_bytes_per_second),
            "Live",
        )
        table.add_row(
            "Download",
            format_rate(snapshot.network_speed.download_bytes_per_second),
            "Live",
        )

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
                thresholds.gpu.warning,
                thresholds.gpu.critical,
            )
            gpu_table.add_row(
                gpu.name,
                f"{gpu.usage_percent:.1f}%",
                f"{gpu.temperature_celsius:.1f}°C",
                f"{gpu.vram_used_mib:.0f} / {gpu.vram_total_mib:.0f} MiB",
                f"{gpu.power_watts:.2f} W" if gpu.power_watts is not None else "Unavailable",
                _status_text(gpu_status),
            )

    renderables = [table, gpu_table]
    if active_alerts is not None:
        renderables.append(_build_alerts_view(active_alerts, enabled=config.alerts.enabled))
    return Group(*renderables)


def _build_alerts_view(
    alerts: tuple[ActiveAlert, ...],
    *,
    enabled: bool,
) -> Table:
    table = Table(title="Alerts", expand=True)
    table.add_column("Severity", style="bold")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    if not enabled:
        table.add_row("Disabled", "Alert evaluation is disabled", "—")
    elif not alerts:
        table.add_row(Text("Healthy", style="green"), "No active alerts", "—")
    else:
        for alert in alerts:
            style = "bold red" if alert.severity is AlertSeverity.CRITICAL else "yellow"
            table.add_row(
                Text(alert.severity.value.upper(), style=style),
                alert.label,
                f"{alert.current_value:.1f}{alert.unit}",
            )
    return table


def print_snapshot(
    snapshot: SystemSnapshot,
    config: AppConfig,
    *,
    show_network_speed: bool = False,
) -> None:
    console.print(build_snapshot_view(snapshot, config, show_network_speed=show_network_speed))


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
