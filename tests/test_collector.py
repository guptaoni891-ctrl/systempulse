from __future__ import annotations

from types import SimpleNamespace

import systempulse.collector as collector


def test_get_disk_root_windows_uses_system_drive(monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Windows")
    monkeypatch.setenv("SystemDrive", "D:")

    assert collector._get_disk_root() == "D:\\"


def test_get_disk_root_unix_uses_root(monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Darwin")

    assert collector._get_disk_root() == "/"


def test_cpu_temperature_returns_none_when_platform_has_no_sensor_api(monkeypatch):
    def unsupported():
        raise AttributeError("temperature sensors unavailable")

    monkeypatch.setattr(collector.psutil, "sensors_temperatures", unsupported, raising=False)

    assert collector._get_cpu_temperature({"temperature": {"preferred_sensors": []}}) is None


def test_cpu_temperature_uses_preferred_sensor(monkeypatch):
    reading = SimpleNamespace(current=61.5, label="Tctl")
    monkeypatch.setattr(
        collector.psutil,
        "sensors_temperatures",
        lambda: {"k10temp": [reading]},
        raising=False,
    )

    config = {"temperature": {"preferred_sensors": ["k10temp"]}}

    assert collector._get_cpu_temperature(config) == 61.5
