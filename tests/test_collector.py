from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import systempulse.collector as collector
from systempulse.config import AppConfig, MonitorConfig, TemperatureConfig
from systempulse.models import DiagnosticKind, NetworkStats


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


def test_cpu_temperature_reports_unavailable_when_sensor_attribute_is_absent(monkeypatch):
    monkeypatch.delattr(collector.psutil, "sensors_temperatures", raising=False)

    temperature, diagnostics = collector._collect_cpu_temperature(AppConfig())

    assert temperature is None
    assert diagnostics[0].kind is DiagnosticKind.UNAVAILABLE


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
    virtual_memory = Mock(return_value=SimpleNamespace(percent=50.0, used=4_000, total=8_000))
    disk_usage = Mock(return_value=SimpleNamespace(percent=40.0, used=40_000, total=100_000))
    get_network_totals = Mock(return_value=NetworkStats(bytes_sent=1_000, bytes_received=2_000))
    monkeypatch.setattr(collector.psutil, "cpu_percent", cpu_percent)
    monkeypatch.setattr(collector.psutil, "virtual_memory", virtual_memory)
    monkeypatch.setattr(collector.psutil, "disk_usage", disk_usage)
    monkeypatch.setattr(collector, "get_network_totals", get_network_totals)
    return cpu_percent, virtual_memory, disk_usage, get_network_totals


def _collector_config():
    return AppConfig(
        monitor=MonitorConfig(cpu_sample_interval=0.25),
        temperature=TemperatureConfig(preferred_sensors=("k10temp",)),
    )


def test_collect_complete_core_metrics_with_windows_drive(monkeypatch):
    cpu_percent, virtual_memory, disk_usage, get_network_totals = _mock_system_metrics(monkeypatch)
    monkeypatch.setattr(collector.platform, "system", lambda: "Windows")
    monkeypatch.setenv("SystemDrive", "E:")
    monkeypatch.setattr(collector, "_collect_cpu_temperature", Mock(return_value=(61.5, ())))

    metrics = collector.collect_core_metrics(_collector_config())

    assert metrics.cpu_usage_percent == 12.5
    assert metrics.ram_usage_percent == 50.0
    assert metrics.ram_used_bytes == 4_000
    assert metrics.ram_total_bytes == 8_000
    assert metrics.disk_usage_percent == 40.0
    assert metrics.disk_used_bytes == 40_000
    assert metrics.disk_total_bytes == 100_000
    assert metrics.cpu_temperature_celsius == 61.5
    assert metrics.network.bytes_sent == 1_000
    assert metrics.network.bytes_received == 2_000
    assert metrics.diagnostics == ()
    cpu_percent.assert_called_once_with(interval=0.25)
    virtual_memory.assert_called_once_with()
    disk_usage.assert_called_once_with("E:\\")
    get_network_totals.assert_called_once_with()


def test_collect_core_metrics_records_unavailable_temperature(monkeypatch):
    _mock_system_metrics(monkeypatch)
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.psutil, "sensors_temperatures", lambda: {}, raising=False)

    metrics = collector.collect_core_metrics(_collector_config())

    assert metrics.cpu_temperature_celsius is None
    assert metrics.diagnostics[0].collector == "cpu_temperature"
    assert metrics.diagnostics[0].kind is DiagnosticKind.UNAVAILABLE
    collector.psutil.disk_usage.assert_called_once_with("/")


def test_malformed_temperature_is_nonfatal_and_diagnostic(monkeypatch):
    reading = SimpleNamespace(current="invalid", label="CPU package")
    monkeypatch.setattr(
        collector.psutil,
        "sensors_temperatures",
        lambda: {"coretemp": [reading]},
        raising=False,
    )

    temperature, diagnostics = collector._collect_cpu_temperature(_collector_config())

    assert temperature is None
    assert diagnostics[0].kind is DiagnosticKind.MALFORMED_RESULT
