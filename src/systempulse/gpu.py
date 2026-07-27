from __future__ import annotations

import subprocess

from systempulse.models import GPUStats

QUERY_FIELDS = (
    "name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw"
)


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
                usage_percent=float(_parse_number(usage)),
                temperature_celsius=float(_parse_number(temperature)),
                vram_used_mib=float(_parse_number(used)),
                vram_total_mib=float(_parse_number(total)),
                power_watts=_parse_number(power, allow_none=True),
            )
        )

    return tuple(gpus)


def get_gpu_stats(timeout: float = 3.0) -> tuple[GPUStats, ...]:
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
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ()

    try:
        return parse_nvidia_smi_output(result.stdout.strip())
    except ValueError:
        return ()
