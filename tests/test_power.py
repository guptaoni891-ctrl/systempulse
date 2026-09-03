import json
import subprocess

import pytest

import systempulse.power as power
from systempulse.config import PowerConfig
from systempulse.models import DiagnosticKind, GPUStats
from systempulse.power import (
    aggregate_gpu_power,
    calculate_power_stats,
    collect_cpu_package_power,
    parse_lhm_output,
    parse_lhm_sensor_output,
    select_cpu_package_sensor,
)


def _sensor(
    name="CPU Package",
    value=46.2,
    *,
    identifier="/intelcpu/0/power/0",
    parent="/intelcpu/0",
    sensor_type="Power",
):
    return {
        "Name": name,
        "SensorType": sensor_type,
        "Value": value,
        "Identifier": identifier,
        "Parent": parent,
    }


def _hardware(
    identifier="/intelcpu/0",
    hardware_type="Cpu",
    name="Test CPU",
):
    return {
        "Name": name,
        "HardwareType": hardware_type,
        "Identifier": identifier,
    }


def _lhm_output(sensors, hardware=None):
    return json.dumps(
        {
            "Hardware": hardware if hardware is not None else [_hardware()],
            "Sensors": sensors if isinstance(sensors, list) else [sensors],
        }
    )


def _gpu(power_watts, name="Test GPU"):
    return GPUStats(name, 25.0, 55.0, 512.0, 4_096.0, power_watts)


def _mock_windows_run(monkeypatch, *, stdout):
    monkeypatch.setattr(power.platform, "system", lambda: "Windows")
    completed = subprocess.CompletedProcess("powershell.exe", 0, stdout=stdout, stderr="")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return completed

    monkeypatch.setattr(power.subprocess, "run", run)
    return calls


def test_valid_cpu_ppt_sensor_is_preferred_and_subprocess_is_safe(monkeypatch):
    output = _lhm_output([_sensor("CPU Package", 40.0), _sensor("CPU PPT", 52.5)])
    calls = _mock_windows_run(monkeypatch, stdout=output)

    result = collect_cpu_package_power(timeout=1.25)

    assert result.cpu_package_watts == 52.5
    assert result.source == "LibreHardwareMonitor"
    assert result.diagnostics == ()
    command, kwargs = calls[0]
    assert command[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    assert "root\\LibreHardwareMonitor" in command[4]
    assert "ClassName Hardware" in command[4]
    assert "HardwareType" in command[4]
    assert "ClassName Sensor" in command[4]
    assert "SensorType = 'Power'" in command[4]
    assert kwargs == {
        "capture_output": True,
        "text": True,
        "check": True,
        "timeout": 1.25,
    }


def test_valid_cpu_package_sensor_is_selected(monkeypatch):
    _mock_windows_run(monkeypatch, stdout=_lhm_output(_sensor("CPU Package", 44.0)))

    result = collect_cpu_package_power()

    assert result.cpu_package_watts == 44.0


def test_total_power_is_selected_only_with_clear_cpu_hardware_context(monkeypatch):
    _mock_windows_run(
        monkeypatch,
        stdout=_lhm_output(
            _sensor(
                "Total Power",
                38.0,
                identifier="/amdcpu/0/power/0",
                parent="/amdcpu/0",
            ),
            [_hardware("/amdcpu/0")],
        ),
    )

    result = collect_cpu_package_power()

    assert result.cpu_package_watts == 38.0


def test_ambiguous_total_power_is_not_selected(monkeypatch):
    _mock_windows_run(
        monkeypatch,
        stdout=_lhm_output(
            _sensor("Total Power", 38.0, identifier="/board/0/power/0", parent=""),
            [_hardware("/amdcpu/0")],
        ),
    )

    result = collect_cpu_package_power()

    assert result.cpu_package_watts is None
    assert result.diagnostics[0].kind is DiagnosticKind.UNAVAILABLE


def test_real_amd_hardware_package_sensor_regression(monkeypatch):
    output = _lhm_output(
        [
            _sensor(
                "Package",
                24.10229,
                identifier="/amdcpu/0/power/0",
                parent="/amdcpu/0",
            ),
            _sensor(
                "Core #1 (SMU)",
                1.061627,
                identifier="/amdcpu/0/power/1",
                parent="/amdcpu/0",
            ),
            _sensor(
                "GPU Package",
                7.004,
                identifier="/gpu-nvidia/0/power/0",
                parent="/gpu-nvidia/0",
            ),
            _sensor(
                "GPU Core",
                1.0,
                identifier="/gpu-amd/0/power/0",
                parent="/gpu-amd/0",
            ),
        ],
        [
            _hardware("/amdcpu/0", "Cpu", "AMD Ryzen 7 7800X3D"),
            _hardware("/gpu-nvidia/0", "GpuNvidia", "NVIDIA GeForce RTX 5070"),
            _hardware("/gpu-amd/0", "GpuAmd", "AMD Radeon(TM) Graphics"),
        ],
    )
    _mock_windows_run(monkeypatch, stdout=output)

    result = collect_cpu_package_power()

    assert result.cpu_package_watts == 24.10229
    assert result.source == "LibreHardwareMonitor"


def test_generic_package_sensor_owned_by_gpu_is_not_selected(monkeypatch):
    output = _lhm_output(
        _sensor(
            "Package",
            7.004,
            identifier="/gpu-nvidia/0/power/0",
            parent="/gpu-nvidia/0",
        ),
        [
            _hardware("/amdcpu/0", "Cpu"),
            _hardware("/gpu-nvidia/0", "GpuNvidia"),
        ],
    )
    _mock_windows_run(monkeypatch, stdout=output)

    result = collect_cpu_package_power()

    assert result.cpu_package_watts is None
    assert result.diagnostics[0].kind is DiagnosticKind.UNAVAILABLE


def test_cpu_core_power_sensors_are_not_selected_or_summed(monkeypatch):
    output = _lhm_output(
        [
            _sensor("Core #1 (SMU)", 1.0, parent="/amdcpu/0"),
            _sensor("Core #2 (SMU)", 2.0, parent="/amdcpu/0"),
        ],
        [_hardware("/amdcpu/0")],
    )
    _mock_windows_run(monkeypatch, stdout=output)

    result = collect_cpu_package_power()

    assert result.cpu_package_watts is None


def test_non_power_sensor_is_ignored_by_parser():
    sensors = parse_lhm_sensor_output(json.dumps(_sensor(sensor_type="Temperature")))

    assert sensors == ()


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (FileNotFoundError("powershell.exe"), DiagnosticKind.COMMAND_MISSING),
        (subprocess.TimeoutExpired("powershell.exe", 3.0), DiagnosticKind.TIMEOUT),
        (subprocess.CalledProcessError(7, "powershell.exe"), DiagnosticKind.UNAVAILABLE),
        (OSError("permission denied"), DiagnosticKind.EXECUTION_FAILED),
    ],
)
def test_cpu_power_subprocess_failures_are_diagnostics(monkeypatch, error, kind):
    monkeypatch.setattr(power.platform, "system", lambda: "Windows")

    def failed(*args, **kwargs):
        raise error

    monkeypatch.setattr(power.subprocess, "run", failed)

    result = collect_cpu_package_power()

    assert result.cpu_package_watts is None
    assert result.source is None
    assert result.diagnostics[0].collector == "cpu_power"
    assert result.diagnostics[0].kind is kind
    assert len(result.diagnostics[0].message) < 160


def test_lhm_nonzero_error_does_not_include_large_stderr(monkeypatch):
    monkeypatch.setattr(power.platform, "system", lambda: "Windows")
    error = subprocess.CalledProcessError(
        1,
        "powershell.exe",
        stderr="private and noisy output " * 1_000,
    )

    def failed(*args, **kwargs):
        raise error

    monkeypatch.setattr(power.subprocess, "run", failed)

    result = collect_cpu_package_power()

    assert "private and noisy" not in result.diagnostics[0].message


@pytest.mark.parametrize(
    "output",
    [
        "not json",
        "42",
        _lhm_output(_sensor("CPU Package", "bad")),
        _lhm_output(_sensor("", 10)),
        json.dumps({"Hardware": [42], "Sensors": []}),
        _lhm_output([], [_hardware(identifier="")]),
    ],
)
def test_malformed_lhm_output_returns_diagnostic(monkeypatch, output):
    _mock_windows_run(monkeypatch, stdout=output)

    result = collect_cpu_package_power()

    assert result.cpu_package_watts is None
    assert result.diagnostics[0].kind is DiagnosticKind.MALFORMED_RESULT


def test_empty_lhm_output_reports_unavailable_sensor(monkeypatch):
    _mock_windows_run(monkeypatch, stdout="")

    result = collect_cpu_package_power()

    assert result.diagnostics[0].kind is DiagnosticKind.UNAVAILABLE


def test_non_windows_cpu_power_is_unavailable_without_running_subprocess(monkeypatch):
    monkeypatch.setattr(power.platform, "system", lambda: "Linux")

    def unexpected_run(*args, **kwargs):
        pytest.fail("subprocess should not run on non-Windows platforms")

    monkeypatch.setattr(power.subprocess, "run", unexpected_run)

    result = collect_cpu_package_power()

    assert result.cpu_package_watts is None
    assert result.diagnostics[0].kind is DiagnosticKind.UNAVAILABLE


def test_sensor_parser_and_selector_accept_cpu_parent_context():
    sensors = parse_lhm_sensor_output(
        json.dumps(_sensor("Total Power", 33.3, identifier="/power/0", parent="/processor/0"))
    )

    selected = select_cpu_package_sensor(sensors, frozenset({"/processor/0"}))

    assert selected is not None
    assert selected.value == 33.3


def test_combined_parser_identifies_only_cpu_hardware():
    output = _lhm_output(
        _sensor("Package", 24.0, parent="/amdcpu/0"),
        [
            _hardware("/amdcpu/0", "cPu"),
            _hardware("/gpu-amd/0", "GpuAmd"),
        ],
    )

    cpu_identifiers, sensors = parse_lhm_output(output)

    assert cpu_identifiers == frozenset({"/amdcpu/0"})
    assert len(sensors) == 1


def test_gpu_power_aggregation_handles_single_multiple_and_missing_values():
    assert aggregate_gpu_power((_gpu(42.5),)) == 42.5
    assert aggregate_gpu_power((_gpu(42.5), _gpu(57.5), _gpu(None))) == 100.0
    assert aggregate_gpu_power((_gpu(None),)) is None
    assert aggregate_gpu_power(()) is None


def test_power_calculations_require_both_cpu_and_gpu_and_apply_configuration():
    stats = calculate_power_stats(
        46.2,
        "LibreHardwareMonitor",
        (_gpu(40.0), _gpu(47.5)),
        PowerConfig(other_components_watts=35.0, psu_efficiency=0.90),
    )

    assert stats.cpu_package_watts == 46.2
    assert stats.gpu_total_watts == 87.5
    assert stats.cpu_gpu_watts == pytest.approx(133.7)
    assert stats.estimated_system_watts == pytest.approx(168.7)
    assert stats.estimated_wall_watts == pytest.approx(168.7 / 0.90)
    assert stats.actual_wall_watts is None
    assert stats.cpu_source == "LibreHardwareMonitor"


@pytest.mark.parametrize(
    ("cpu_watts", "gpus"),
    [
        (None, (_gpu(50.0),)),
        (40.0, (_gpu(None),)),
        (40.0, ()),
    ],
)
def test_unavailable_component_prevents_complete_and_estimated_totals(cpu_watts, gpus):
    stats = calculate_power_stats(cpu_watts, "provider", gpus, PowerConfig())

    assert stats.cpu_gpu_watts is None
    assert stats.estimated_system_watts is None
    assert stats.estimated_wall_watts is None
    assert stats.cpu_source == ("provider" if cpu_watts is not None else None)


def test_disabled_power_calculation_returns_only_unavailable_values():
    stats = calculate_power_stats(
        40.0,
        "provider",
        (_gpu(50.0),),
        PowerConfig(enabled=False),
    )

    assert stats.cpu_package_watts is None
    assert stats.gpu_total_watts is None
    assert stats.actual_wall_watts is None
