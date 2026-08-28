from __future__ import annotations

import subprocess
from typing import Literal, overload

from systempulse.models import (
    CollectionDiagnostic,
    DiagnosticKind,
    GPUCollection,
    GPUStats,
)

QUERY_FIELDS = "name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw"


@overload
def _parse_number(value: str, *, allow_none: Literal[False] = False) -> float: ...


@overload
def _parse_number(value: str, *, allow_none: Literal[True]) -> float | None: ...


def _parse_number(value: str, *, allow_none: bool = False) -> float | None:
    cleaned = value.strip()
    if cleaned in {"", "N/A", "[N/A]", "Not Supported"}:
        if allow_none:
            return None
        raise ValueError(f"Expected a number, received {cleaned!r}.")
    return float(cleaned)


def parse_nvidia_smi_output(output: str) -> tuple[GPUStats, ...]:
    gpus: list[GPUStats] = []

    for line in output.splitlines():
        if not line.strip():
            continue

        values = [item.strip() for item in line.split(",")]
        if len(values) != 6:
            raise ValueError(f"Unexpected nvidia-smi row: {line!r}")

        name, usage, temperature, used, total, power = values
        gpus.append(
            GPUStats(
                name=name,
                usage_percent=_parse_number(usage),
                temperature_celsius=_parse_number(temperature),
                vram_used_mib=_parse_number(used),
                vram_total_mib=_parse_number(total),
                power_watts=_parse_number(power, allow_none=True),
            )
        )

    return tuple(gpus)


def collect_gpu_stats(timeout: float = 3.0) -> GPUCollection:
    command = [
        "nvidia-smi",
        f"--query-gpu={QUERY_FIELDS}",
        "--format=csv,noheader,nounits",
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
        return GPUCollection(
            gpus=(),
            diagnostics=(
                CollectionDiagnostic(
                    collector="gpu",
                    kind=DiagnosticKind.COMMAND_MISSING,
                    message="nvidia-smi is not installed or is not on PATH.",
                ),
            ),
        )
    except subprocess.TimeoutExpired:
        return GPUCollection(
            gpus=(),
            diagnostics=(
                CollectionDiagnostic(
                    collector="gpu",
                    kind=DiagnosticKind.TIMEOUT,
                    message=f"nvidia-smi exceeded its {timeout:g} second timeout.",
                ),
            ),
        )
    except subprocess.CalledProcessError as error:
        return GPUCollection(
            gpus=(),
            diagnostics=(
                CollectionDiagnostic(
                    collector="gpu",
                    kind=DiagnosticKind.EXECUTION_FAILED,
                    message=f"nvidia-smi exited with status {error.returncode}.",
                ),
            ),
        )
    except OSError as error:
        return GPUCollection(
            gpus=(),
            diagnostics=(
                CollectionDiagnostic(
                    collector="gpu",
                    kind=DiagnosticKind.EXECUTION_FAILED,
                    message=f"Could not execute nvidia-smi: {error}",
                ),
            ),
        )

    output = result.stdout.strip()
    if not output:
        return GPUCollection(
            gpus=(),
            diagnostics=(
                CollectionDiagnostic(
                    collector="gpu",
                    kind=DiagnosticKind.MALFORMED_RESULT,
                    message="nvidia-smi returned no GPU rows.",
                ),
            ),
        )
    try:
        return GPUCollection(gpus=parse_nvidia_smi_output(output))
    except ValueError as error:
        return GPUCollection(
            gpus=(),
            diagnostics=(
                CollectionDiagnostic(
                    collector="gpu",
                    kind=DiagnosticKind.MALFORMED_RESULT,
                    message=f"Could not parse nvidia-smi output: {error}",
                ),
            ),
        )


def get_gpu_stats(timeout: float = 3.0) -> tuple[GPUStats, ...]:
    """Return GPU metrics while preserving the v1 tuple-only API."""
    return collect_gpu_stats(timeout).gpus
