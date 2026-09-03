from __future__ import annotations

import json
import math
import platform
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from systempulse.config import PowerConfig
from systempulse.models import (
    CollectionDiagnostic,
    CPUPowerCollection,
    DiagnosticKind,
    GPUStats,
    PowerStats,
)

CPU_POWER_COLLECTOR = "cpu_power"
CPU_POWER_SOURCE = "LibreHardwareMonitor"

_POWERSHELL_SCRIPT = """
$hardware = @(Get-CimInstance -Namespace 'root\\LibreHardwareMonitor' -ClassName Hardware `
    -ErrorAction Stop | Select-Object Name, HardwareType, Identifier)
$sensors = @(Get-CimInstance -Namespace 'root\\LibreHardwareMonitor' -ClassName Sensor `
    -Filter \"SensorType = 'Power'\" -ErrorAction Stop |
    Select-Object Name, SensorType, Value, Identifier, Parent)
[PSCustomObject]@{ Hardware = $hardware; Sensors = $sensors } |
    ConvertTo-Json -Compress -Depth 3
""".strip()


@dataclass(frozen=True, slots=True)
class _PowerSensor:
    name: str
    value: float
    identifier: str
    parent: str


def _diagnostic(kind: DiagnosticKind, message: str) -> CPUPowerCollection:
    return CPUPowerCollection(
        diagnostics=(
            CollectionDiagnostic(
                collector=CPU_POWER_COLLECTOR,
                kind=kind,
                message=message,
            ),
        )
    )


def _text_field(record: Mapping[str, Any], name: str) -> str:
    value = record.get(name, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"LibreHardwareMonitor {name} must be text.")
    return value.strip()


def _power_value(record: Mapping[str, Any]) -> float:
    raw_value = record.get("Value")
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise ValueError("LibreHardwareMonitor Value must be numeric.")
    value = float(raw_value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("LibreHardwareMonitor Value must be a finite non-negative number.")
    return value


def _records(value: Any, name: str) -> list[Mapping[str, Any]]:
    records = value if isinstance(value, list) else [value]
    if any(not isinstance(record, Mapping) for record in records):
        raise ValueError(f"LibreHardwareMonitor returned a non-object {name} record.")
    return records


def _parse_power_sensors(raw: Any) -> tuple[_PowerSensor, ...]:
    sensors: list[_PowerSensor] = []
    for record in _records(raw, "sensor"):
        sensor_type = _text_field(record, "SensorType")
        if sensor_type.casefold() != "power":
            continue
        name = _text_field(record, "Name")
        if not name:
            raise ValueError("LibreHardwareMonitor returned a Power sensor without a name.")
        sensors.append(
            _PowerSensor(
                name=name,
                value=_power_value(record),
                identifier=_text_field(record, "Identifier"),
                parent=_text_field(record, "Parent"),
            )
        )
    return tuple(sensors)


def parse_lhm_sensor_output(output: str) -> tuple[_PowerSensor, ...]:
    """Parse Power sensors returned by LibreHardwareMonitor's WMI provider."""
    if not output.strip():
        return ()

    try:
        raw: Any = json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError("LibreHardwareMonitor returned invalid JSON.") from error

    return _parse_power_sensors(raw)


def parse_lhm_output(output: str) -> tuple[frozenset[str], tuple[_PowerSensor, ...]]:
    """Parse LibreHardwareMonitor hardware ownership and Power sensor data."""
    if not output.strip():
        return frozenset(), ()

    try:
        raw: Any = json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError("LibreHardwareMonitor returned invalid JSON.") from error
    if not isinstance(raw, Mapping) or "Hardware" not in raw or "Sensors" not in raw:
        raise ValueError("LibreHardwareMonitor returned an invalid hardware/sensor payload.")

    cpu_identifiers: set[str] = set()
    for record in _records(raw["Hardware"], "hardware"):
        if _text_field(record, "HardwareType").casefold() != "cpu":
            continue
        identifier = _text_field(record, "Identifier")
        if not identifier:
            raise ValueError("LibreHardwareMonitor returned CPU hardware without an identifier.")
        cpu_identifiers.add(identifier.casefold())

    return frozenset(cpu_identifiers), _parse_power_sensors(raw["Sensors"])


def _normalized(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def _cpu_sensor_rank(name: str) -> int | None:
    name = _normalized(name)
    if name == "cpu ppt" or name.startswith("cpu ppt "):
        return 0
    if name == "cpu package" or name.startswith("cpu package "):
        return 1
    if name == "package":
        return 2
    if name == "total power":
        return 3
    return None


def select_cpu_package_sensor(
    sensors: Iterable[_PowerSensor],
    cpu_hardware_identifiers: frozenset[str],
) -> _PowerSensor | None:
    """Choose the most specific CPU package sensor without accepting GPU power."""
    selected: _PowerSensor | None = None
    selected_rank: int | None = None
    for sensor in sensors:
        if sensor.parent.casefold() not in cpu_hardware_identifiers:
            continue
        rank = _cpu_sensor_rank(sensor.name)
        if rank is not None and (selected_rank is None or rank < selected_rank):
            selected = sensor
            selected_rank = rank
    return selected


def collect_cpu_package_power(timeout: float = 3.0) -> CPUPowerCollection:
    """Collect Windows CPU package power from an optional LibreHardwareMonitor provider."""
    if platform.system() != "Windows":
        return _diagnostic(
            DiagnosticKind.UNAVAILABLE,
            "CPU package power collection is currently supported only on Windows.",
        )

    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        _POWERSHELL_SCRIPT,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return _diagnostic(
            DiagnosticKind.COMMAND_MISSING,
            "Windows PowerShell is not installed or is not on PATH.",
        )
    except subprocess.TimeoutExpired:
        return _diagnostic(
            DiagnosticKind.TIMEOUT,
            f"LibreHardwareMonitor query exceeded its {timeout:g} second timeout.",
        )
    except subprocess.CalledProcessError as error:
        return _diagnostic(
            DiagnosticKind.UNAVAILABLE,
            "LibreHardwareMonitor WMI is unavailable "
            f"(PowerShell exited with status {error.returncode}).",
        )
    except OSError:
        return _diagnostic(
            DiagnosticKind.EXECUTION_FAILED,
            "Could not execute Windows PowerShell for CPU package power.",
        )

    try:
        cpu_hardware_identifiers, sensors = parse_lhm_output(result.stdout)
    except (TypeError, ValueError):
        return _diagnostic(
            DiagnosticKind.MALFORMED_RESULT,
            "LibreHardwareMonitor returned malformed CPU power sensor data.",
        )

    sensor = select_cpu_package_sensor(sensors, cpu_hardware_identifiers)
    if sensor is None:
        return _diagnostic(
            DiagnosticKind.UNAVAILABLE,
            "LibreHardwareMonitor did not expose a recognized CPU package power sensor.",
        )
    return CPUPowerCollection(
        cpu_package_watts=sensor.value,
        source=CPU_POWER_SOURCE,
    )


def aggregate_gpu_power(gpus: Iterable[GPUStats]) -> float | None:
    """Sum all NVIDIA GPU power readings that are available."""
    values = [gpu.power_watts for gpu in gpus if gpu.power_watts is not None]
    return sum(values) if values else None


def calculate_power_stats(
    cpu_package_watts: float | None,
    cpu_source: str | None,
    gpus: Iterable[GPUStats],
    config: PowerConfig,
) -> PowerStats:
    """Build measured and explicitly estimated power values without polling hardware."""
    if not config.enabled:
        return PowerStats()

    gpu_total_watts = aggregate_gpu_power(gpus)
    cpu_gpu_watts = (
        cpu_package_watts + gpu_total_watts
        if cpu_package_watts is not None and gpu_total_watts is not None
        else None
    )
    estimated_system_watts = (
        cpu_gpu_watts + config.other_components_watts if cpu_gpu_watts is not None else None
    )
    estimated_wall_watts = (
        estimated_system_watts / config.psu_efficiency
        if estimated_system_watts is not None
        else None
    )
    return PowerStats(
        cpu_package_watts=cpu_package_watts,
        gpu_total_watts=gpu_total_watts,
        cpu_gpu_watts=cpu_gpu_watts,
        estimated_system_watts=estimated_system_watts,
        estimated_wall_watts=estimated_wall_watts,
        actual_wall_watts=None,
        cpu_source=cpu_source if cpu_package_watts is not None else None,
    )
