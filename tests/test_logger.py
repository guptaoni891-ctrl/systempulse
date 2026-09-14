import csv
from datetime import UTC, datetime

import pytest

from systempulse.logger import CSV_HEADER, LEGACY_CSV_HEADER, POWER_CSV_HEADER, save_snapshot
from systempulse.models import (
    GPUStats,
    NetworkSpeed,
    NetworkStats,
    PowerStats,
    SystemSnapshot,
)


def _gpu(name="GPU One", power_watts=42.5):
    return GPUStats(
        name=name,
        usage_percent=25.0,
        temperature_celsius=55.0,
        vram_used_mib=512.0,
        vram_total_mib=4096.0,
        power_watts=power_watts,
    )


def _snapshot(*, temperature=61.5, gpus=(), speed=None, power=None):
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
        power=power or PowerStats(),
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
    assert rows[0][-7:] == POWER_CSV_HEADER
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
    assert row[13:19] == ["Unavailable"] * 6
    assert row[19:] == ["Unavailable"] * 7


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


def test_v2_power_fields_and_source_are_written_directly_from_snapshot(tmp_path):
    path = tmp_path / "readings.csv"
    power = PowerStats(
        cpu_package_watts=42.5,
        gpu_total_watts=121.8,
        cpu_gpu_watts=164.3,
        estimated_system_watts=199.3,
        estimated_wall_watts=221.44,
        actual_wall_watts=None,
        cpu_source="LibreHardwareMonitor",
    )

    save_snapshot(_snapshot(gpus=(_gpu(power_watts=77.0),), power=power), path)
    row = _read_rows(path)[1]

    assert row[18] == "77.0"
    assert row[19:] == [
        "42.5",
        "121.8",
        "164.3",
        "199.3",
        "221.44",
        "Unavailable",
        "LibreHardwareMonitor",
    ]


def test_existing_empty_csv_receives_v2_header_and_row(tmp_path):
    path = tmp_path / "empty.csv"
    path.touch()

    save_snapshot(_snapshot(), path)

    rows = _read_rows(path)
    assert rows[0] == CSV_HEADER
    assert len(rows[1]) == len(CSV_HEADER)


def test_existing_v2_csv_appends_matching_width_rows(tmp_path):
    path = tmp_path / "v2.csv"
    save_snapshot(_snapshot(), path)

    save_snapshot(_snapshot(power=PowerStats(cpu_package_watts=10.0)), path)

    rows = _read_rows(path)
    assert rows.count(CSV_HEADER) == 1
    assert len(rows) == 3
    assert all(len(row) == len(CSV_HEADER) for row in rows)
    assert rows[2][19] == "10.0"


def test_existing_legacy_csv_receives_only_legacy_width_row(tmp_path):
    path = tmp_path / "legacy.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        csv.writer(file).writerow(LEGACY_CSV_HEADER)

    save_snapshot(
        _snapshot(power=PowerStats(cpu_package_watts=42.5, cpu_source="provider")),
        path,
    )

    rows = _read_rows(path)
    assert rows[0] == LEGACY_CSV_HEADER
    assert len(rows[1]) == len(LEGACY_CSV_HEADER)
    assert "cpu_package_watts" not in rows[0]
    assert "42.5" not in rows[1]
    assert "provider" not in rows[1]


def test_unknown_existing_csv_header_is_rejected_without_modifying_file(tmp_path):
    path = tmp_path / "unknown.csv"
    original = "timestamp,unexpected_column\nexisting,data\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="incompatible header"):
        save_snapshot(_snapshot(), path)

    assert path.read_text(encoding="utf-8") == original


def test_custom_nested_output_path_is_created(tmp_path):
    path = tmp_path / "nested" / "logs" / "custom.csv"

    returned = save_snapshot(_snapshot(speed=NetworkSpeed(1.0, 2.0)), path)

    assert returned == path
    assert path.is_file()
