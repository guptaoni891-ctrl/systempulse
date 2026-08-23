from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import systempulse.collector as collector
from systempulse.config import AppConfig, MonitorConfig, TemperatureConfig
from systempulse.models import GPUStats


def test_get_disk_root_windows_uses_system_drive(monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Windows")
    monkeypatch.setenv("SystemDrive", "D:")

    assert collector._get_disk_root() == "D:\\"


def test_get_disk_root_unix_uses_root(monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Darwin")

    assert collector._get_disk_root() == "/"


def test_get_disk_root_linux_uses_root(monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")

    assert collector._get_disk_root() == "/"


def test_cpu_temperature_returns_none_when_platform_has_no_sensor_api(monkeypatch):
    def unsupported():
        raise AttributeError("temperature sensors unavailable")

    monkeypatch.setattr(collector.psutil, "sensors_temperatures", unsupported, raising=False)

    config = AppConfig(temperature=TemperatureConfig(preferred_sensors=()))
    assert collector._get_cpu_temperature(config) is None


def test_cpu_temperature_uses_preferred_sensor(monkeypatch):
    reading = SimpleNamespace(current=61.5, label="Tctl")
    monkeypatch.setattr(
        collector.psutil,
        "sensors_temperatures",
        lambda: {"k10temp": [reading]},
        raising=False,
    )

    config = AppConfig(temperature=TemperatureConfig(preferred_sensors=("k10temp",)))

    assert collector._get_cpu_temperature(config) == 61.5


def _mock_system_metrics(monkeypatch):
    cpu_percent = Mock(return_value=12.5)
    virtual_memory = Mock(
        return_value=SimpleNamespace(percent=50.0, used=4_000, total=8_000)
    )
    disk_usage = Mock(
        return_value=SimpleNamespace(percent=40.0, used=40_000, total=100_000)
    )
    net_io_counters = Mock(return_value=SimpleNamespace(bytes_sent=1_000, bytes_recv=2_000))
    monkeypatch.setattr(collector.psutil, "cpu_percent", cpu_percent)
    monkeypatch.setattr(collector.psutil, "virtual_memory", virtual_memory)
    monkeypatch.setattr(collector.psutil, "disk_usage", disk_usage)
    monkeypatch.setattr(collector.psutil, "net_io_counters", net_io_counters)
    return cpu_percent, virtual_memory, disk_usage, net_io_counters


def _collector_config():
    return AppConfig(
        monitor=MonitorConfig(cpu_sample_interval=0.25),
        temperature=TemperatureConfig(preferred_sensors=("k10temp",)),
    )


def test_collect_complete_system_snapshot_with_windows_drive(monkeypatch):
    cpu_percent, virtual_memory, disk_usage, net_io_counters = _mock_system_metrics(
        monkeypatch
    )
    gpu_stats = (
        GPUStats(
            name="Test GPU",
            usage_percent=30.0,
            temperature_celsius=50.0,
            vram_used_mib=1_024.0,
            vram_total_mib=4_096.0,
            power_watts=60.0,
        ),
    )
    get_gpu_stats = Mock(return_value=gpu_stats)
    monkeypatch.setattr(collector.platform, "system", lambda: "Windows")
    monkeypatch.setenv("SystemDrive", "E:")
    monkeypatch.setattr(collector, "_get_cpu_temperature", Mock(return_value=61.5))
    monkeypatch.setattr(collector, "get_gpu_stats", get_gpu_stats)

    snapshot = collector.collect_system_snapshot(_collector_config())

    assert isinstance(snapshot.timestamp, datetime)
    assert snapshot.timestamp.microsecond == 0
    assert snapshot.cpu_usage_percent == 12.5
    assert snapshot.ram_usage_percent == 50.0
    assert snapshot.ram_used_bytes == 4_000
    assert snapshot.ram_total_bytes == 8_000
    assert snapshot.disk_usage_percent == 40.0
    assert snapshot.disk_used_bytes == 40_000
    assert snapshot.disk_total_bytes == 100_000
    assert snapshot.cpu_temperature_celsius == 61.5
    assert snapshot.network.bytes_sent == 1_000
    assert snapshot.network.bytes_received == 2_000
    assert snapshot.gpus == gpu_stats
    cpu_percent.assert_called_once_with(interval=0.25)
    virtual_memory.assert_called_once_with()
    disk_usage.assert_called_once_with("E:\\")
    net_io_counters.assert_called_once_with(pernic=False, nowrap=True)
    get_gpu_stats.assert_called_once_with()


def test_collect_snapshot_with_unavailable_temperature_and_gpu(monkeypatch):
    _mock_system_metrics(monkeypatch)
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector, "_get_cpu_temperature", Mock(return_value=None))
    monkeypatch.setattr(collector, "get_gpu_stats", Mock(return_value=()))

    snapshot = collector.collect_system_snapshot(_collector_config())

    assert snapshot.cpu_temperature_celsius is None
    assert snapshot.gpus == ()
    collector.psutil.disk_usage.assert_called_once_with("/")


def test_collect_snapshot_skips_gpu_probe_when_disabled(monkeypatch):
    _mock_system_metrics(monkeypatch)
    monkeypatch.setattr(collector, "_get_disk_root", Mock(return_value="/"))
    monkeypatch.setattr(collector, "_get_cpu_temperature", Mock(return_value=None))
    get_gpu_stats = Mock()
    monkeypatch.setattr(collector, "get_gpu_stats", get_gpu_stats)

    snapshot = collector.collect_system_snapshot(_collector_config(), include_gpu=False)

    assert snapshot.gpus == ()
    get_gpu_stats.assert_not_called()
