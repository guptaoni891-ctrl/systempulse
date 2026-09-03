from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from systempulse.paths import (
    ConfigPath,
    default_history_database,
    resolve_config_path,
    user_config_path,
)


class ConfigError(ValueError):
    """Raised when configuration cannot be loaded, validated, or safely updated."""


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a number.")
    result = float(value)
    if not math.isfinite(result):
        raise ConfigError(f"{name} must be a finite number.")
    return result


def _percentage(value: Any, name: str) -> float:
    result = _number(value, name)
    if not 0 <= result <= 100:
        raise ConfigError(f"{name} must be between 0 and 100.")
    return result


def _positive_number(value: Any, name: str, *, allow_zero: bool = False) -> float:
    result = _number(value, name)
    valid = result >= 0 if allow_zero else result > 0
    if not valid:
        qualifier = "zero or greater" if allow_zero else "greater than zero"
        raise ConfigError(f"{name} must be {qualifier}.")
    return result


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer.")
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero.")
    return int(value)


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be a Boolean.")
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{name} must be a JSON object.")
    return value


def _reject_unknown(mapping: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        fields = ", ".join(unknown)
        raise ConfigError(f"Unknown {name} setting(s): {fields}.")


@dataclass(frozen=True, slots=True)
class MetricThresholds:
    warning: float
    critical: float

    def __post_init__(self) -> None:
        warning = _percentage(self.warning, "warning threshold")
        critical = _percentage(self.critical, "critical threshold")
        if warning >= critical:
            raise ConfigError("Warning threshold must be lower than critical threshold.")
        object.__setattr__(self, "warning", warning)
        object.__setattr__(self, "critical", critical)


@dataclass(frozen=True, slots=True)
class ThresholdsConfig:
    cpu: MetricThresholds = field(default_factory=lambda: MetricThresholds(60, 80))
    memory: MetricThresholds = field(default_factory=lambda: MetricThresholds(75, 90))
    disk: MetricThresholds = field(default_factory=lambda: MetricThresholds(80, 90))
    temperature: MetricThresholds = field(default_factory=lambda: MetricThresholds(70, 85))
    gpu: MetricThresholds = field(default_factory=lambda: MetricThresholds(75, 90))


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    refresh_interval: float = 2.0
    cpu_sample_interval: float = 0.2

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "refresh_interval",
            _positive_number(self.refresh_interval, "monitor.refresh_interval"),
        )
        object.__setattr__(
            self,
            "cpu_sample_interval",
            _positive_number(
                self.cpu_sample_interval,
                "monitor.cpu_sample_interval",
                allow_zero=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    csv_path: str = "system_log.csv"

    def __post_init__(self) -> None:
        if not isinstance(self.csv_path, str) or not self.csv_path.strip():
            raise ConfigError("logging.csv_path must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class ProcessesConfig:
    limit: int = 5
    sample_interval: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "limit", _positive_integer(self.limit, "processes.limit"))
        object.__setattr__(
            self,
            "sample_interval",
            _positive_number(self.sample_interval, "processes.sample_interval"),
        )


@dataclass(frozen=True, slots=True)
class TemperatureConfig:
    preferred_sensors: tuple[str, ...] = (
        "k10temp",
        "coretemp",
        "zenpower",
        "cpu_thermal",
    )

    def __post_init__(self) -> None:
        sensors = self.preferred_sensors
        if not isinstance(sensors, (list, tuple)):
            raise ConfigError("temperature.preferred_sensors must be a list of strings.")
        if any(not isinstance(sensor, str) or not sensor.strip() for sensor in sensors):
            raise ConfigError("temperature.preferred_sensors must contain non-empty strings.")
        object.__setattr__(self, "preferred_sensors", tuple(sensors))


@dataclass(frozen=True, slots=True)
class AlertRuleConfig:
    warning: float
    critical: float
    enabled: bool = True
    duration: float = 0.0
    cooldown: float = 60.0
    hysteresis: float = 5.0

    def __post_init__(self) -> None:
        enabled = _boolean(self.enabled, "alert rule enabled")
        warning = _percentage(self.warning, "alert warning threshold")
        critical = _percentage(self.critical, "alert critical threshold")
        duration = _positive_number(
            self.duration,
            "alert duration",
            allow_zero=True,
        )
        cooldown = _positive_number(
            self.cooldown,
            "alert cooldown",
            allow_zero=True,
        )
        hysteresis = _positive_number(
            self.hysteresis,
            "alert hysteresis",
            allow_zero=True,
        )
        if warning >= critical:
            raise ConfigError("Alert warning threshold must be lower than critical threshold.")
        if hysteresis >= warning:
            raise ConfigError("Alert hysteresis must be lower than the warning threshold.")
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "warning", warning)
        object.__setattr__(self, "critical", critical)
        object.__setattr__(self, "duration", duration)
        object.__setattr__(self, "cooldown", cooldown)
        object.__setattr__(self, "hysteresis", hysteresis)


@dataclass(frozen=True, slots=True)
class AlertsConfig:
    enabled: bool = True
    history_limit: int = 100
    cpu: AlertRuleConfig = field(default_factory=lambda: AlertRuleConfig(60, 80))
    memory: AlertRuleConfig = field(default_factory=lambda: AlertRuleConfig(75, 90))
    disk: AlertRuleConfig = field(default_factory=lambda: AlertRuleConfig(80, 90))
    cpu_temperature: AlertRuleConfig = field(default_factory=lambda: AlertRuleConfig(70, 85))
    gpu_usage: AlertRuleConfig = field(default_factory=lambda: AlertRuleConfig(75, 90))
    gpu_temperature: AlertRuleConfig = field(default_factory=lambda: AlertRuleConfig(70, 85))

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", _boolean(self.enabled, "alerts.enabled"))
        object.__setattr__(
            self,
            "history_limit",
            _positive_integer(self.history_limit, "alerts.history_limit"),
        )


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    enabled: bool = True
    database: str = field(default_factory=lambda: str(default_history_database()))
    retention_days: int = 30

    def __post_init__(self) -> None:
        enabled = _boolean(self.enabled, "history.enabled")
        if not isinstance(self.database, str) or not self.database.strip():
            raise ConfigError("history.database must be a non-empty path string.")
        if "\x00" in self.database:
            raise ConfigError("history.database must not contain null characters.")
        retention_days = _positive_integer(
            self.retention_days,
            "history.retention_days",
        )
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "retention_days", retention_days)


@dataclass(frozen=True, slots=True)
class PrometheusConfig:
    host: str = "127.0.0.1"
    port: int = 9100
    interval: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ConfigError("prometheus.host must be a non-empty string.")
        if self.host != self.host.strip() or any(character.isspace() for character in self.host):
            raise ConfigError("prometheus.host must not contain whitespace.")
        if "://" in self.host or "/" in self.host or "\\" in self.host or "\x00" in self.host:
            raise ConfigError(
                "prometheus.host must be a hostname or IP address, not a URL or path."
            )
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ConfigError("prometheus.port must be an integer.")
        if not 1 <= self.port <= 65_535:
            raise ConfigError("prometheus.port must be between 1 and 65535.")
        object.__setattr__(
            self,
            "interval",
            _positive_number(self.interval, "prometheus.interval"),
        )


@dataclass(frozen=True, slots=True)
class PowerConfig:
    enabled: bool = True
    other_components_watts: float = 35.0
    psu_efficiency: float = 0.90

    def __post_init__(self) -> None:
        enabled = _boolean(self.enabled, "power.enabled")
        other_components_watts = _positive_number(
            self.other_components_watts,
            "power.other_components_watts",
            allow_zero=True,
        )
        psu_efficiency = _positive_number(self.psu_efficiency, "power.psu_efficiency")
        if psu_efficiency > 1:
            raise ConfigError("power.psu_efficiency must be at most 1.")
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "other_components_watts", other_components_watts)
        object.__setattr__(self, "psu_efficiency", psu_efficiency)


@dataclass(frozen=True, slots=True)
class AppConfig:
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    processes: ProcessesConfig = field(default_factory=ProcessesConfig)
    temperature: TemperatureConfig = field(default_factory=TemperatureConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    prometheus: PrometheusConfig = field(default_factory=PrometheusConfig)
    power: PowerConfig = field(default_factory=PowerConfig)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AppConfig:
        root = _mapping(raw, "configuration")
        _reject_unknown(
            root,
            {
                "thresholds",
                "monitor",
                "logging",
                "processes",
                "temperature",
                "alerts",
                "history",
                "prometheus",
                "power",
            },
            "top-level",
        )

        defaults = cls()
        thresholds_raw = _mapping(root.get("thresholds", {}), "thresholds")
        threshold_keys = {
            f"{name}_{level}"
            for name in ("cpu", "memory", "disk", "temperature", "gpu")
            for level in ("warning", "critical")
        }
        _reject_unknown(thresholds_raw, threshold_keys, "thresholds")

        def metric(name: str, default: MetricThresholds) -> MetricThresholds:
            return MetricThresholds(
                warning=_percentage(
                    thresholds_raw.get(f"{name}_warning", default.warning),
                    f"thresholds.{name}_warning",
                ),
                critical=_percentage(
                    thresholds_raw.get(f"{name}_critical", default.critical),
                    f"thresholds.{name}_critical",
                ),
            )

        monitor_raw = _mapping(root.get("monitor", {}), "monitor")
        _reject_unknown(monitor_raw, {"refresh_interval", "cpu_sample_interval"}, "monitor")
        logging_raw = _mapping(root.get("logging", {}), "logging")
        _reject_unknown(logging_raw, {"csv_path"}, "logging")
        processes_raw = _mapping(root.get("processes", {}), "processes")
        _reject_unknown(processes_raw, {"limit", "sample_interval"}, "processes")
        temperature_raw = _mapping(root.get("temperature", {}), "temperature")
        _reject_unknown(temperature_raw, {"preferred_sensors"}, "temperature")
        alerts_raw = _mapping(root.get("alerts", {}), "alerts")
        alert_rule_names = {
            "cpu",
            "memory",
            "disk",
            "cpu_temperature",
            "gpu_usage",
            "gpu_temperature",
        }
        _reject_unknown(alerts_raw, {"enabled", "history_limit", *alert_rule_names}, "alerts")
        history_raw = _mapping(root.get("history", {}), "history")
        _reject_unknown(
            history_raw,
            {"enabled", "database", "retention_days"},
            "history",
        )
        prometheus_raw = _mapping(root.get("prometheus", {}), "prometheus")
        _reject_unknown(
            prometheus_raw,
            {"host", "port", "interval"},
            "prometheus",
        )
        power_raw = _mapping(root.get("power", {}), "power")
        _reject_unknown(
            power_raw,
            {"enabled", "other_components_watts", "psu_efficiency"},
            "power",
        )

        def alert_rule(name: str, default: AlertRuleConfig) -> AlertRuleConfig:
            rule_raw = _mapping(alerts_raw.get(name, {}), f"alerts.{name}")
            _reject_unknown(
                rule_raw,
                {"enabled", "warning", "critical", "duration", "cooldown", "hysteresis"},
                f"alerts.{name}",
            )
            return AlertRuleConfig(
                enabled=rule_raw.get("enabled", default.enabled),
                warning=rule_raw.get("warning", default.warning),
                critical=rule_raw.get("critical", default.critical),
                duration=rule_raw.get("duration", default.duration),
                cooldown=rule_raw.get("cooldown", default.cooldown),
                hysteresis=rule_raw.get("hysteresis", default.hysteresis),
            )

        return cls(
            thresholds=ThresholdsConfig(
                cpu=metric("cpu", defaults.thresholds.cpu),
                memory=metric("memory", defaults.thresholds.memory),
                disk=metric("disk", defaults.thresholds.disk),
                temperature=metric("temperature", defaults.thresholds.temperature),
                gpu=metric("gpu", defaults.thresholds.gpu),
            ),
            monitor=MonitorConfig(
                refresh_interval=monitor_raw.get(
                    "refresh_interval", defaults.monitor.refresh_interval
                ),
                cpu_sample_interval=monitor_raw.get(
                    "cpu_sample_interval", defaults.monitor.cpu_sample_interval
                ),
            ),
            logging=LoggingConfig(csv_path=logging_raw.get("csv_path", defaults.logging.csv_path)),
            processes=ProcessesConfig(
                limit=processes_raw.get("limit", defaults.processes.limit),
                sample_interval=processes_raw.get(
                    "sample_interval", defaults.processes.sample_interval
                ),
            ),
            temperature=TemperatureConfig(
                preferred_sensors=temperature_raw.get(
                    "preferred_sensors", defaults.temperature.preferred_sensors
                )
            ),
            alerts=AlertsConfig(
                enabled=alerts_raw.get("enabled", defaults.alerts.enabled),
                history_limit=alerts_raw.get("history_limit", defaults.alerts.history_limit),
                cpu=alert_rule("cpu", defaults.alerts.cpu),
                memory=alert_rule("memory", defaults.alerts.memory),
                disk=alert_rule("disk", defaults.alerts.disk),
                cpu_temperature=alert_rule("cpu_temperature", defaults.alerts.cpu_temperature),
                gpu_usage=alert_rule("gpu_usage", defaults.alerts.gpu_usage),
                gpu_temperature=alert_rule("gpu_temperature", defaults.alerts.gpu_temperature),
            ),
            history=HistoryConfig(
                enabled=history_raw.get("enabled", defaults.history.enabled),
                database=history_raw.get("database", defaults.history.database),
                retention_days=history_raw.get("retention_days", defaults.history.retention_days),
            ),
            prometheus=PrometheusConfig(
                host=prometheus_raw.get("host", defaults.prometheus.host),
                port=prometheus_raw.get("port", defaults.prometheus.port),
                interval=prometheus_raw.get("interval", defaults.prometheus.interval),
            ),
            power=PowerConfig(
                enabled=power_raw.get("enabled", defaults.power.enabled),
                other_components_watts=power_raw.get(
                    "other_components_watts", defaults.power.other_components_watts
                ),
                psu_efficiency=power_raw.get(
                    "psu_efficiency", defaults.power.psu_efficiency
                ),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "thresholds": {
                "cpu_warning": self.thresholds.cpu.warning,
                "cpu_critical": self.thresholds.cpu.critical,
                "memory_warning": self.thresholds.memory.warning,
                "memory_critical": self.thresholds.memory.critical,
                "disk_warning": self.thresholds.disk.warning,
                "disk_critical": self.thresholds.disk.critical,
                "temperature_warning": self.thresholds.temperature.warning,
                "temperature_critical": self.thresholds.temperature.critical,
                "gpu_warning": self.thresholds.gpu.warning,
                "gpu_critical": self.thresholds.gpu.critical,
            },
            "monitor": {
                "refresh_interval": self.monitor.refresh_interval,
                "cpu_sample_interval": self.monitor.cpu_sample_interval,
            },
            "logging": {"csv_path": self.logging.csv_path},
            "processes": {
                "limit": self.processes.limit,
                "sample_interval": self.processes.sample_interval,
            },
            "temperature": {"preferred_sensors": list(self.temperature.preferred_sensors)},
            "alerts": {
                "enabled": self.alerts.enabled,
                "history_limit": self.alerts.history_limit,
                **{
                    name: {
                        "enabled": rule.enabled,
                        "warning": rule.warning,
                        "critical": rule.critical,
                        "duration": rule.duration,
                        "cooldown": rule.cooldown,
                        "hysteresis": rule.hysteresis,
                    }
                    for name, rule in (
                        ("cpu", self.alerts.cpu),
                        ("memory", self.alerts.memory),
                        ("disk", self.alerts.disk),
                        ("cpu_temperature", self.alerts.cpu_temperature),
                        ("gpu_usage", self.alerts.gpu_usage),
                        ("gpu_temperature", self.alerts.gpu_temperature),
                    )
                },
            },
            "history": {
                "enabled": self.history.enabled,
                "database": self.history.database,
                "retention_days": self.history.retention_days,
            },
            "prometheus": {
                "host": self.prometheus.host,
                "port": self.prometheus.port,
                "interval": self.prometheus.interval,
            },
            "power": {
                "enabled": self.power.enabled,
                "other_components_watts": self.power.other_components_watts,
                "psu_efficiency": self.power.psu_efficiency,
            },
        }


DEFAULT_CONFIG = AppConfig()


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    config: AppConfig
    resolution: ConfigPath


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except json.JSONDecodeError as error:
        raise ConfigError(
            f"{path} contains invalid JSON at line {error.lineno}, column {error.colno}."
        ) from error
    except OSError as error:
        raise ConfigError(f"Could not read {path}: {error}") from error

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object.")
    return raw


def load_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> LoadedConfig:
    resolution = resolve_config_path(path, environ=environ, cwd=cwd)
    if not resolution.exists:
        if resolution.source in {"explicit", "environment"}:
            raise ConfigError(f"Configuration file not found: {resolution.path}")
        return LoadedConfig(config=DEFAULT_CONFIG, resolution=resolution)

    raw = _read_mapping(resolution.path)
    try:
        config = AppConfig.from_mapping(raw)
    except ConfigError as error:
        raise ConfigError(f"Invalid configuration in {resolution.path}: {error}") from error
    return LoadedConfig(config=config, resolution=resolution)


def _write_mapping_atomic(path: Path, raw: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
        )
        temporary_path = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            json.dump(raw, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    except OSError as error:
        raise ConfigError(f"Could not write {path}: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def initialize_config(path: str | Path | None = None, *, force: bool = False) -> Path:
    target = user_config_path() if path is None else Path(path).expanduser()
    target = target.resolve(strict=False)
    if target.exists() and not force:
        raise ConfigError(f"Configuration file already exists: {target}")
    _write_mapping_atomic(target, DEFAULT_CONFIG.to_dict())
    return target


SETTING_PATHS: dict[str, tuple[str, ...]] = {
    "cpu.warning": ("thresholds", "cpu_warning"),
    "cpu.critical": ("thresholds", "cpu_critical"),
    "ram.warning": ("thresholds", "memory_warning"),
    "ram.critical": ("thresholds", "memory_critical"),
    "memory.warning": ("thresholds", "memory_warning"),
    "memory.critical": ("thresholds", "memory_critical"),
    "disk.warning": ("thresholds", "disk_warning"),
    "disk.critical": ("thresholds", "disk_critical"),
    "temperature.warning": ("thresholds", "temperature_warning"),
    "temperature.critical": ("thresholds", "temperature_critical"),
    "gpu.warning": ("thresholds", "gpu_warning"),
    "gpu.critical": ("thresholds", "gpu_critical"),
    "monitor.refresh_interval": ("monitor", "refresh_interval"),
    "monitor.cpu_sample_interval": ("monitor", "cpu_sample_interval"),
    "logging.csv_path": ("logging", "csv_path"),
    "processes.limit": ("processes", "limit"),
    "processes.sample_interval": ("processes", "sample_interval"),
    "temperature.preferred_sensors": ("temperature", "preferred_sensors"),
    "alerts.enabled": ("alerts", "enabled"),
    "alerts.history_limit": ("alerts", "history_limit"),
    "history.enabled": ("history", "enabled"),
    "history.database": ("history", "database"),
    "history.retention_days": ("history", "retention_days"),
    "prometheus.host": ("prometheus", "host"),
    "prometheus.port": ("prometheus", "port"),
    "prometheus.interval": ("prometheus", "interval"),
    "power.enabled": ("power", "enabled"),
    "power.other_components_watts": ("power", "other_components_watts"),
    "power.psu_efficiency": ("power", "psu_efficiency"),
}

for _rule_name in (
    "cpu",
    "memory",
    "disk",
    "cpu_temperature",
    "gpu_usage",
    "gpu_temperature",
):
    for _field_name in (
        "enabled",
        "warning",
        "critical",
        "duration",
        "cooldown",
        "hysteresis",
    ):
        SETTING_PATHS[f"alerts.{_rule_name}.{_field_name}"] = (
            "alerts",
            _rule_name,
            _field_name,
        )


def _parse_setting_value(raw_value: str) -> Any:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value


def set_config_value(path: str | Path, key: str, raw_value: str) -> AppConfig:
    target = Path(path).expanduser().resolve(strict=False)
    setting_path = SETTING_PATHS.get(key)
    if setting_path is None:
        supported = ", ".join(sorted(SETTING_PATHS))
        raise ConfigError(f"Unsupported setting {key!r}. Supported settings: {supported}")

    raw = _read_mapping(target) if target.is_file() else {}
    candidate = deepcopy(raw)
    section = candidate
    for section_name in setting_path[:-1]:
        child = section.setdefault(section_name, {})
        if not isinstance(child, dict):
            raise ConfigError(f"{section_name} must be a JSON object.")
        section = child
    section[setting_path[-1]] = _parse_setting_value(raw_value)
    config = AppConfig.from_mapping(candidate)
    _write_mapping_atomic(target, candidate)
    return config
