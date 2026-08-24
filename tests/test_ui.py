from datetime import UTC, datetime
from io import StringIO

from rich.console import Console

from systempulse.config import AlertsConfig, AppConfig
from systempulse.models import (
    ActiveAlert,
    AlertSeverity,
    NetworkSpeed,
    NetworkStats,
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


def _render(*, show_network_speed, active_alerts=None, config=None):
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)
    console.print(
        build_snapshot_view(
            _snapshot(),
            config or AppConfig(),
            show_network_speed=show_network_speed,
            active_alerts=active_alerts,
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
