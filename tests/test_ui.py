from datetime import UTC, datetime
from io import StringIO

from rich.console import Console

from systempulse.config import AppConfig
from systempulse.models import NetworkSpeed, NetworkStats, SystemSnapshot
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


def _render(*, show_network_speed):
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)
    console.print(
        build_snapshot_view(
            _snapshot(),
            AppConfig(),
            show_network_speed=show_network_speed,
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
