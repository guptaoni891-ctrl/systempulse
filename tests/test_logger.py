import csv
from datetime import UTC, datetime

from systempulse.logger import CSV_HEADER, save_snapshot
from systempulse.models import GPUStats, NetworkSpeed, NetworkStats, SystemSnapshot


def _gpu(name="GPU One", power_watts=42.5):
    return GPUStats(
        name=name,
        usage_percent=25.0,
        temperature_celsius=55.0,
        vram_used_mib=512.0,
        vram_total_mib=4096.0,
        power_watts=power_watts,
    )


def _snapshot(*, temperature=61.5, gpus=(), speed=None):
    return SystemSnapshot(
        timestamp=datetime(2026, 8, 23, 12, 30, 45, tzinfo=UTC),
        cpu_usage_percent=12.5,
        ram_usage_percent=50.0,
        ram_used_bytes=4_000,
        ram_total_bytes=8_000,
        disk_usage_percent=40.0,
        disk_used_bytes=40_000,
        disk_total_bytes=100_000,
        cpu_temperature_celsius=temperature,
        network=NetworkStats(bytes_sent=1_000, bytes_received=2_000),
        network_speed=speed or NetworkSpeed(100.125, 200.456),
        gpus=tuple(gpus),
    )


def _read_rows(path):
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.reader(file))


def test_save_snapshot_creates_file_and_header(tmp_path):
    path = tmp_path / "readings.csv"

    returned = save_snapshot(_snapshot(), path)
    rows = _read_rows(path)

    assert returned == path
    assert rows[0] == CSV_HEADER
    assert len(rows) == 2
    assert rows[1][0] == "2026-08-23 12:30:45+00:00"
    assert rows[1][11:13] == ["100.12", "200.46"]


def test_save_snapshot_appends_readings_without_repeating_header(tmp_path):
    path = tmp_path / "readings.csv"
    speed = NetworkSpeed(10.0, 20.0)

    save_snapshot(_snapshot(speed=speed), path)
    save_snapshot(_snapshot(temperature=62.0, speed=speed), path)
    rows = _read_rows(path)

    assert len(rows) == 3
    assert rows.count(CSV_HEADER) == 1
    assert rows[1][8] == "61.5"
    assert rows[2][8] == "62.0"


def test_optional_temperature_and_no_gpu_are_recorded_as_unavailable(tmp_path):
    path = tmp_path / "readings.csv"

    save_snapshot(_snapshot(temperature=None, speed=NetworkSpeed(0.0, 0.0)), path)
    row = _read_rows(path)[1]

    assert row[8] == "Unavailable"
    assert row[13:] == ["Unavailable"] * 6


def test_gpu_fields_include_optional_missing_power(tmp_path):
    path = tmp_path / "readings.csv"

    save_snapshot(
        _snapshot(gpus=(_gpu(name="GPU, Experimental", power_watts=None),)),
        path,
    )
    row = _read_rows(path)[1]

    assert row[13] == "GPU, Experimental"
    assert row[14:18] == ["25.0", "55.0", "512.0", "4096.0"]
    assert row[18] == "Unavailable"


def test_csv_currently_records_only_first_gpu(tmp_path):
    """Protect the v1.1 first-GPU-only CSV behavior until the format is redesigned."""
    path = tmp_path / "readings.csv"

    save_snapshot(
        _snapshot(gpus=(_gpu("First GPU"), _gpu("Second GPU"))),
        path,
    )
    rows = _read_rows(path)

    assert len(rows) == 2
    assert rows[1][13] == "First GPU"
    assert "Second GPU" not in rows[1]


def test_custom_nested_output_path_is_created(tmp_path):
    path = tmp_path / "nested" / "logs" / "custom.csv"

    returned = save_snapshot(_snapshot(speed=NetworkSpeed(1.0, 2.0)), path)

    assert returned == path
    assert path.is_file()
