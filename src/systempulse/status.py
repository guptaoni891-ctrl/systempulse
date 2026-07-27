from __future__ import annotations


def classify(value: float, warning: float, critical: float) -> str:
    if warning >= critical:
        raise ValueError("Warning threshold must be lower than critical threshold.")

    if value >= critical:
        return "Critical"
    if value >= warning:
        return "High"
    return "Normal"


def classify_temperature(value: float, warning: float, critical: float) -> str:
    status = classify(value, warning, critical)
    return "Hot" if status == "High" else status
