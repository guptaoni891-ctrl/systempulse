from __future__ import annotations

import math
from datetime import datetime

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from systempulse.config import AppConfig
from systempulse.models import (
    ActiveAlert,
    AlertEvent,
    AlertSeverity,
    HistoricalSample,
    HistorySummary,
    PowerHistorySummary,
    PowerSessionStats,
    ProcessStats,
    SystemSnapshot,
)
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
    history_warning: str | None = None,
    power_session: PowerSessionStats | None = None,
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

    power_table = Table(title="Power", expand=True)
    power_table.add_column("Metric", style="bold")
    power_table.add_column("Value")
    power_table.add_column("Source")
    power = snapshot.power

    power_table.add_row(
        "CPU Package",
        _format_power(power.cpu_package_watts),
        power.cpu_source or "—",
    )
    power_table.add_row("GPU Total", _format_power(power.gpu_total_watts), "nvidia-smi")
    power_table.add_row(
        "CPU + GPU",
        _format_power(power.cpu_gpu_watts),
        "Measured components",
    )
    power_table.add_row(
        "Estimated System",
        _format_power(power.estimated_system_watts, estimated=True),
        "Estimate",
    )
    power_table.add_row(
        "Estimated Wall",
        _format_power(power.estimated_wall_watts, estimated=True),
        "Estimate",
    )
    power_table.add_row(
        "Actual Wall",
        _format_power(power.actual_wall_watts),
        "External provider",
    )

    renderables: list[RenderableType] = [table, gpu_table, power_table]
    if power_session is not None:
        renderables.append(_build_power_session_view(power_session))
    if active_alerts is not None:
        renderables.append(_build_alerts_view(active_alerts, enabled=config.alerts.enabled))
    if history_warning is not None:
        renderables.append(Panel(history_warning, title="History warning", style="yellow"))
    return Group(*renderables)


def _build_power_session_view(session: PowerSessionStats) -> Table:
    table = Table(title="Power Session", expand=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Current CPU", _format_power(session.current_cpu_package_watts))
    table.add_row("Current GPU", _format_power(session.current_gpu_total_watts))
    table.add_row("Current CPU + GPU", _format_power(session.current_cpu_gpu_watts))
    table.add_row(
        "Estimated System",
        _format_power(session.current_estimated_system_watts, estimated=True),
    )
    table.add_row(
        "Estimated Wall",
        _format_power(session.current_estimated_wall_watts, estimated=True),
    )
    table.add_row(
        "Average Estimated Wall",
        _format_power(session.average_estimated_wall_watts, estimated=True),
    )
    table.add_row(
        "Peak Estimated Wall",
        _format_power(session.peak_estimated_wall_watts, estimated=True),
    )
    table.add_row("Session Duration", format_duration(session.session_duration_seconds))
    table.add_row(
        "Estimated Observed Duration",
        format_duration(session.estimated_wall_observed_duration_seconds),
    )
    table.add_row(
        "Estimated Energy Used",
        _format_energy(session.estimated_wall_energy_wh, estimated=True),
    )

    if session.peak_actual_wall_watts is None:
        table.add_row("Actual Wall", "Unavailable")
    else:
        table.add_row("Actual Wall", _format_power(session.current_actual_wall_watts))
        table.add_row(
            "Average Actual Wall",
            _format_power(session.average_actual_wall_watts),
        )
        table.add_row("Peak Actual Wall", _format_power(session.peak_actual_wall_watts))
        table.add_row(
            "Actual Observed Duration",
            format_duration(session.actual_wall_observed_duration_seconds),
        )
        table.add_row(
            "Actual Energy Used",
            _format_energy(session.actual_wall_energy_wh),
        )
    return table


def _format_power(value: float | None, *, estimated: bool = False) -> str:
    if value is None:
        return "Unavailable"
    prefix = "~" if estimated else ""
    return f"{prefix}{value:.1f} W"


def _format_energy(energy_wh: float, *, estimated: bool = False) -> str:
    prefix = "~" if estimated else ""
    if energy_wh < 1000.0:
        return f"{prefix}{energy_wh:.1f} Wh"
    return f"{prefix}{energy_wh / 1000.0:.3f} kWh"


def format_duration(duration_seconds: float) -> str:
    """Format a non-negative duration without noisy fractional seconds."""
    if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
        return "0s"
    total_seconds = int(duration_seconds)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


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


def print_history(
    summary: HistorySummary,
    samples: tuple[HistoricalSample, ...],
    database: str,
) -> None:
    console.print(f"History database: [bold]{database}[/bold]")
    table = Table(title="History Summary", expand=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    if summary.sample_count == 0:
        table.add_row("Samples", "0")
    else:
        table.add_row("Period start", _utc_text(summary.period_start))
        table.add_row("Period end", _utc_text(summary.period_end))
        table.add_row("Samples", str(summary.sample_count))
        table.add_row("Average CPU", _percent(summary.average_cpu_percent))
        table.add_row("Peak CPU", _percent(summary.peak_cpu_percent))
        table.add_row("Average memory", _percent(summary.average_memory_percent))
        table.add_row("Peak memory", _percent(summary.peak_memory_percent))
        table.add_row("Average disk", _percent(summary.average_disk_percent))
        table.add_row("Peak disk", _percent(summary.peak_disk_percent))
        table.add_row(
            "Peak CPU temperature",
            _temperature(summary.peak_cpu_temperature_celsius),
        )
        table.add_row(
            "Peak GPU temperature",
            _temperature(summary.peak_gpu_temperature_celsius),
        )
        table.add_row(
            "Observed sent counter change",
            _optional_bytes(summary.observed_network_sent_change_bytes),
        )
        table.add_row(
            "Observed received counter change",
            _optional_bytes(summary.observed_network_received_change_bytes),
        )
        table.add_row("Alert events", str(summary.alert_event_count))
    console.print(table)
    console.print(_build_power_history_view(summary.power))

    recent = Table(title="Recent Samples", expand=True)
    recent.add_column("UTC timestamp")
    recent.add_column("CPU", justify="right")
    recent.add_column("Memory", justify="right")
    recent.add_column("Disk", justify="right")
    recent.add_column("CPU temp", justify="right")
    recent.add_column("Upload", justify="right")
    recent.add_column("Download", justify="right")
    recent.add_column("GPUs", justify="right")
    if not samples:
        recent.add_row("No samples", "—", "—", "—", "—", "—", "—", "—")
    else:
        for sample in samples:
            recent.add_row(
                _utc_text(sample.timestamp),
                _percent(sample.cpu_usage_percent),
                _percent(sample.memory_usage_percent),
                _percent(sample.disk_usage_percent),
                _temperature(sample.cpu_temperature_celsius),
                format_rate(sample.upload_bytes_per_second),
                format_rate(sample.download_bytes_per_second),
                str(sample.gpu_count),
            )
    console.print(recent)
    console.print(_build_recent_power_samples_view(samples))


def _build_power_history_view(power: PowerHistorySummary) -> Table:
    table = Table(title="Power History", expand=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("CPU average", _format_power(power.average_cpu_package_watts))
    table.add_row("CPU peak", _format_power(power.peak_cpu_package_watts))
    table.add_row("GPU average", _format_power(power.average_gpu_total_watts))
    table.add_row("GPU peak", _format_power(power.peak_gpu_total_watts))
    table.add_row("CPU + GPU average", _format_power(power.average_cpu_gpu_watts))
    table.add_row("CPU + GPU peak", _format_power(power.peak_cpu_gpu_watts))
    table.add_row(
        "Estimated system average",
        _format_power(power.average_estimated_system_watts, estimated=True),
    )
    table.add_row(
        "Estimated system peak",
        _format_power(power.peak_estimated_system_watts, estimated=True),
    )
    table.add_row(
        "Estimated wall average",
        _format_power(power.average_estimated_wall_watts, estimated=True),
    )
    table.add_row(
        "Estimated wall peak",
        _format_power(power.peak_estimated_wall_watts, estimated=True),
    )
    table.add_row(
        "Estimated wall energy",
        _format_energy(power.estimated_wall_energy_wh, estimated=True),
    )
    table.add_row(
        "Estimated wall observed duration",
        format_duration(power.estimated_wall_observed_duration_seconds),
    )
    table.add_row(
        "Actual wall average",
        _format_power(power.average_actual_wall_watts),
    )
    table.add_row("Actual wall peak", _format_power(power.peak_actual_wall_watts))
    table.add_row("Actual wall energy", _format_energy(power.actual_wall_energy_wh))
    table.add_row(
        "Actual wall observed duration",
        format_duration(power.actual_wall_observed_duration_seconds),
    )
    return table


def _build_recent_power_samples_view(
    samples: tuple[HistoricalSample, ...],
) -> Table:
    table = Table(title="Recent Power Samples", expand=True)
    table.add_column("UTC timestamp")
    table.add_column("CPU", justify="right")
    table.add_column("GPU", justify="right")
    table.add_column("CPU+GPU", justify="right")
    table.add_column("Est. System", justify="right")
    table.add_column("Est. Wall", justify="right")
    table.add_column("Actual Wall", justify="right")
    if not samples:
        table.add_row("No samples", "—", "—", "—", "—", "—", "—")
    else:
        for sample in samples:
            table.add_row(
                _utc_text(sample.timestamp),
                _format_power(sample.cpu_package_watts),
                _format_power(sample.gpu_total_watts),
                _format_power(sample.cpu_gpu_watts),
                _format_power(sample.estimated_system_watts, estimated=True),
                _format_power(sample.estimated_wall_watts, estimated=True),
                _format_power(sample.actual_wall_watts),
            )
    return table


def print_alert_history(events: tuple[AlertEvent, ...], database: str) -> None:
    console.print(f"History database: [bold]{database}[/bold]")
    table = Table(title="Persisted Alert Events", expand=True)
    table.add_column("UTC timestamp")
    table.add_column("Transition")
    table.add_column("Severity")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    if not events:
        table.add_row("No events", "—", "—", "—", "—")
    else:
        for event in events:
            table.add_row(
                _utc_text(event.timestamp),
                event.transition.value,
                event.severity.value,
                event.label,
                f"{event.current_value:.1f}{event.unit}",
            )
    console.print(table)


def _utc_text(value: datetime | None) -> str:
    return "Unavailable" if value is None else value.strftime("%Y-%m-%d %H:%M:%S UTC")


def _percent(value: float | None) -> str:
    return "Unavailable" if value is None else f"{value:.1f}%"


def _temperature(value: float | None) -> str:
    return "Unavailable" if value is None else f"{value:.1f}°C"


def _optional_bytes(value: int | None) -> str:
    return "Unavailable" if value is None else format_bytes(value)


def print_warning(message: str) -> None:
    console.print(Panel(message, title="Configuration warning", style="yellow"))
