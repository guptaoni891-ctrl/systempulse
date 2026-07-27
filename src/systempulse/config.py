from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "thresholds": {
        "cpu_warning": 60,
        "cpu_critical": 80,
        "memory_warning": 75,
        "memory_critical": 90,
        "disk_warning": 80,
        "disk_critical": 90,
        "temperature_warning": 70,
        "temperature_critical": 85,
        "gpu_warning": 75,
        "gpu_critical": 90,
    },
    "monitor": {
        "refresh_interval": 2.0,
        "cpu_sample_interval": 0.2,
    },
    "logging": {
        "csv_path": "system_log.csv",
    },
    "processes": {
        "limit": 5,
        "sample_interval": 1.0,
    },
    "temperature": {
        "preferred_sensors": ["k10temp", "coretemp", "zenpower", "cpu_thermal"],
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def load_config(path: str | Path = "config.json") -> tuple[dict[str, Any], str | None]:
    config_path = Path(path)

    try:
        with config_path.open("r", encoding="utf-8") as file:
            user_config = json.load(file)
    except FileNotFoundError:
        return deepcopy(DEFAULT_CONFIG), f"{config_path} was not found; defaults are active."
    except json.JSONDecodeError as error:
        message = (
            f"{config_path} contains invalid JSON at line {error.lineno}, "
            f"column {error.colno}; defaults are active."
        )
        return deepcopy(DEFAULT_CONFIG), message
    except OSError as error:
        return deepcopy(DEFAULT_CONFIG), f"Could not read {config_path}: {error}"

    if not isinstance(user_config, dict):
        message = f"{config_path} must contain a JSON object; defaults are active."
        return deepcopy(DEFAULT_CONFIG), message

    return _deep_merge(DEFAULT_CONFIG, user_config), None
