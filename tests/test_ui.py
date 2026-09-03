from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO

from rich.console import Console

import systempulse.ui as ui
from systempulse.config import AlertsConfig, AppConfig
from systempulse.models import (
    ActiveAlert,
    AlertEvent,
    AlertSeverity,
    AlertTransition,
    GPUStats,
    HistoricalSample,
    HistorySummary,
    NetworkSpeed,
    NetworkStats,
    PowerStats,
    ProcessStats,
    SystemSnapshot,
)
from systempulse.ui import build_snapshot_view


def _snapshot():
    return SystemSnapshot(
        timestamp=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        cpu_usage_percent=12.5,
        ram_usage_percent=50.0,
        ram_used_bytes=4_000,
        ram_total_bytes=8_000,
        disk_usage_percent=40.0,
        disk_used_bytes=40_000,
        disk_total_bytes=100_000,
        cpu_temperature_celsius=None,
        network=NetworkStats(bytes_sent=1_000, bytes_received=2_000),
        network_speed=NetworkSpeed(1_024.0, 2_048.0),
        gpus=(),
    )


def _render(
    *,
    show_network_speed,
    active_alerts=None,
    config=None,
    history_warning=None,
):
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)
    console.print(
        build_snapshot_view(
            _snapshot(),
            config or AppConfig(),
            show_network_speed=show_network_speed,
            active_alerts=active_alerts,
            history_warning=history_warning,
        )
    )
    return output.getvalue()


def test_ui_reads_network_rates_from_authoritative_snapshot():
    rendered = _render(show_network_speed=True)

    assert "Upload" in rendered
    assert "1.00 KiB/s" in rendered
    assert "Download" in rendered
    assert "2.00 KiB/s" in rendered


def test_one_time_snapshot_preserves_hidden_rate_rows():
    rendered = _render(show_network_speed=False)

    assert "Network sent" in rendered
    assert "Network received" in rendered
    assert "Upload" not in rendered
    assert "Download" not in rendered
    assert "Alerts" not in rendered


def test_live_alert_section_has_compact_healthy_state():
    rendered = _render(show_network_speed=True, active_alerts=())

    assert "Alerts" in rendered
    assert "Healthy" in rendered
    assert "No active alerts" in rendered


def test_active_warning_and_critical_alerts_are_rendered():
    timestamp = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    alerts = (
        ActiveAlert(
            metric="cpu.usage",
            label="CPU usage",
            severity=AlertSeverity.WARNING,
            current_value=72.5,
            threshold=60,
            unit="%",
            opened_at=timestamp,
            updated_at=timestamp,
        ),
        ActiveAlert(
            metric="gpu.0.temperature",
            label="GPU 0 (Test GPU) temperature",
            severity=AlertSeverity.CRITICAL,
            current_value=90,
            threshold=85,
            unit="°C",
            opened_at=timestamp,
            updated_at=timestamp,
        ),
    )

    rendered = _render(show_network_speed=True, active_alerts=alerts)

    assert "WARNING" in rendered
    assert "CPU usage" in rendered
    assert "72.5%" in rendered
    assert "CRITICAL" in rendered
    assert "GPU 0 (Test GPU) temperature" in rendered
    assert "90.0°C" in rendered


def test_disabled_alert_section_is_explicit_in_live_view():
    config = AppConfig(alerts=AlertsConfig(enabled=False))

    rendered = _render(
        show_network_speed=True,
        active_alerts=(),
        config=config,
    )

    assert "Alert evaluation is disabled" in rendered


def test_history_failure_is_rendered_as_compact_warning():
    rendered = _render(
        show_network_speed=True,
        active_alerts=(),
        history_warning="Database unavailable for this session.",
    )

    assert "History warning" in rendered
    assert "Database unavailable for this session." in rendered


def test_available_temperature_and_gpu_metrics_are_rendered():
    snapshot = replace(
        _snapshot(),
        cpu_temperature_celsius=61.5,
        gpus=(GPUStats("Test GPU", 25.0, 55.0, 512.0, 4_096.0, None),),
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)

    console.print(build_snapshot_view(snapshot, AppConfig()))
    rendered = output.getvalue()

    assert "61.5" in rendered
    assert "Test GPU" in rendered
    assert "512 / 4096 MiB" in rendered
    assert "Unavailable" in rendered


def test_power_panel_distinguishes_measurements_estimates_and_actual_wall_power():
    snapshot = replace(
        _snapshot(),
        power=PowerStats(
            cpu_package_watts=46.2,
            gpu_total_watts=87.5,
            cpu_gpu_watts=133.7,
            estimated_system_watts=168.7,
            estimated_wall_watts=187.4,
            actual_wall_watts=None,
            cpu_source="LibreHardwareMonitor",
        ),
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)

    console.print(build_snapshot_view(snapshot, AppConfig()))
    rendered = output.getvalue()

    assert "Power" in rendered
    assert "CPU Package" in rendered and "46.2 W" in rendered
    assert "GPU Total" in rendered and "87.5 W" in rendered
    assert "CPU + GPU" in rendered and "133.7 W" in rendered
    assert "Estimated System" in rendered and "~168.7 W" in rendered
    assert "Estimated Wall" in rendered and "~187.4 W" in rendered
    assert "Actual Wall" in rendered and "Unavailable" in rendered
    assert "LibreHardwareMonitor" in rendered


def test_power_panel_renders_unavailable_instead_of_zero_for_missing_cpu_power():
    rendered = _render(show_network_speed=False)

    assert "CPU Package" in rendered
    assert "Unavailable" in rendered
    assert "~0.0 W" not in rendered


def test_process_table_and_warning_panel_render(monkeypatch):
    output = StringIO()
    monkeypatch.setattr(ui, "console", Console(file=output, force_terminal=False, width=120))

    ui.print_processes([ProcessStats(123, "python", 12.5, 4.0)])
    ui.print_warning("Configuration fallback active")
    rendered = output.getvalue()

    assert "Top CPU Processes" in rendered
    assert "python" in rendered
    assert "Configuration warning" in rendered


def test_empty_history_and_alert_history_render_clear_states(monkeypatch):
    output = StringIO()
    monkeypatch.setattr(ui, "console", Console(file=output, force_terminal=False, width=120))
    summary = HistorySummary(
        period_start=None,
        period_end=None,
        sample_count=0,
        average_cpu_percent=None,
        peak_cpu_percent=None,
        average_memory_percent=None,
        peak_memory_percent=None,
        average_disk_percent=None,
        peak_disk_percent=None,
        peak_cpu_temperature_celsius=None,
        peak_gpu_temperature_celsius=None,
        observed_network_sent_change_bytes=None,
        observed_network_received_change_bytes=None,
        alert_event_count=0,
    )

    ui.print_history(summary, (), "empty.db")
    ui.print_alert_history((), "empty.db")
    rendered = output.getvalue()

    assert "No samples" in rendered
    assert "No events" in rendered


def test_history_summary_and_recent_samples_render_clear_network_semantics(monkeypatch):
    output = StringIO()
    monkeypatch.setattr(ui, "console", Console(file=output, force_terminal=False, width=140))
    start = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    summary = HistorySummary(
        period_start=start,
        period_end=start,
        sample_count=1,
        average_cpu_percent=20,
        peak_cpu_percent=30,
        average_memory_percent=40,
        peak_memory_percent=50,
        average_disk_percent=60,
        peak_disk_percent=70,
        peak_cpu_temperature_celsius=None,
        peak_gpu_temperature_celsius=80,
        observed_network_sent_change_bytes=None,
        observed_network_received_change_bytes=2_048,
        alert_event_count=1,
    )
    samples = (HistoricalSample(start, 20, 40, 60, None, 1_024, 2_048, 2),)

    ui.print_history(summary, samples, "test.db")
    rendered = output.getvalue()

    assert "Observed sent counter change" in rendered
    assert "Observed received counter change" in rendered
    assert "2.00 KiB" in rendered
    assert "Recent Samples" in rendered
    assert "1.00 KiB/s" in rendered


def test_persisted_alert_history_renders_events(monkeypatch):
    output = StringIO()
    monkeypatch.setattr(ui, "console", Console(file=output, force_terminal=False, width=120))
    timestamp = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    event = AlertEvent(
        timestamp=timestamp,
        metric="cpu.usage",
        label="CPU usage",
        severity=AlertSeverity.WARNING,
        transition=AlertTransition.OPENED,
        current_value=70,
        threshold=60,
        unit="%",
        message="CPU warning",
    )

    ui.print_alert_history((event,), "test.db")
    rendered = output.getvalue()

    assert "Persisted Alert Events" in rendered
    assert "opened" in rendered
    assert "CPU usage" in rendered
    assert "70.0%" in rendered
