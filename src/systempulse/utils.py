from __future__ import annotations


def format_bytes(value: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(value)

    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{size:.2f} TiB"


def format_rate(bytes_per_second: float) -> str:
    return f"{format_bytes(bytes_per_second)}/s"
