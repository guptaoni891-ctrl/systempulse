import json
import os
from pathlib import Path

import pytest

import systempulse.config as config_module
import systempulse.paths as paths
from systempulse.config import (
    DEFAULT_CONFIG,
    AlertRuleConfig,
    AppConfig,
    ConfigError,
    HistoryConfig,
    PowerConfig,
    PrometheusConfig,
    initialize_config,
    load_config,
    set_config_value,
)
from systempulse.paths import default_history_database


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_typed_defaults_match_existing_v1_values():
    config = AppConfig()

    assert config == DEFAULT_CONFIG
    assert config.thresholds.cpu.warning == 60
    assert config.thresholds.cpu.critical == 80
    assert config.thresholds.memory.warning == 75
    assert config.monitor.refresh_interval == 2.0
    assert config.monitor.cpu_sample_interval == 0.2
    assert config.logging.csv_path == "system_log.csv"
    assert config.processes.limit == 5
    assert config.temperature.preferred_sensors[0] == "k10temp"
    assert config.power == PowerConfig(
        enabled=True,
        other_components_watts=35.0,
        psu_efficiency=0.90,
    )


def test_old_configuration_without_power_section_uses_power_defaults():
    config = AppConfig.from_mapping({"monitor": {"refresh_interval": 4}})

    assert config.power == PowerConfig()


def test_partial_power_configuration_deep_merges_defaults():
    config = AppConfig.from_mapping({"power": {"other_components_watts": 50}})

    assert config.power == PowerConfig(
        enabled=True,
        other_components_watts=50.0,
        psu_efficiency=0.90,
    )
    assert config.to_dict()["power"] == {
        "enabled": True,
        "other_components_watts": 50.0,
        "psu_efficiency": 0.90,
    }


@pytest.mark.parametrize(
    "power",
    [
        "enabled",
        {"enabled": "true"},
        {"other_components_watts": -1},
        {"other_components_watts": True},
        {"other_components_watts": float("inf")},
        {"psu_efficiency": 0},
        {"psu_efficiency": -0.1},
        {"psu_efficiency": 1.01},
        {"psu_efficiency": "0.9"},
        {"unsupported": True},
    ],
)
def test_invalid_power_configuration_is_rejected(power):
    with pytest.raises(ConfigError):
        AppConfig.from_mapping({"power": power})


def test_zero_other_component_estimate_and_full_efficiency_are_valid():
    power = PowerConfig(other_components_watts=0, psu_efficiency=1)

    assert power.other_components_watts == 0.0
    assert power.psu_efficiency == 1.0


def test_config_set_supports_power_values(tmp_path):
    path = tmp_path / "config.json"

    set_config_value(path, "power.enabled", "false")
    set_config_value(path, "power.other_components_watts", "42.5")
    config = set_config_value(path, "power.psu_efficiency", "0.85")

    assert config.power == PowerConfig(
        enabled=False,
        other_components_watts=42.5,
        psu_efficiency=0.85,
    )


def test_default_alert_configuration_is_typed_and_enabled():
    alerts = AppConfig().alerts

    assert alerts.enabled is True
    assert alerts.history_limit == 100
    assert alerts.cpu == AlertRuleConfig(60, 80)
    assert alerts.memory.warning == 75
    assert alerts.cpu_temperature.critical == 85
    assert alerts.gpu_usage.enabled is True
    assert alerts.gpu_temperature.hysteresis == 5


def test_default_history_configuration_uses_platform_data_directory():
    history = AppConfig().history

    assert history == HistoryConfig()
    assert history.enabled is True
    assert Path(history.database) == default_history_database()
    assert history.retention_days == 30


def test_partial_history_configuration_deep_merges_defaults(tmp_path):
    database = tmp_path / "custom.db"

    config = AppConfig.from_mapping({"history": {"enabled": False, "database": str(database)}})

    assert config.history.enabled is False
    assert config.history.database == str(database)
    assert config.history.retention_days == 30


@pytest.mark.parametrize(
    "history",
    [
        "enabled",
        {"enabled": "true"},
        {"database": ""},
        {"database": 42},
        {"retention_days": 0},
        {"retention_days": -1},
        {"retention_days": 1.5},
        {"unsupported": True},
    ],
)
def test_invalid_history_configuration_is_rejected(history):
    with pytest.raises(ConfigError):
        AppConfig.from_mapping({"history": history})


def test_partial_alert_configuration_deep_merges_rule_defaults():
    config = AppConfig.from_mapping(
        {
            "alerts": {
                "history_limit": 25,
                "cpu": {"warning": 70, "duration": 15},
                "gpu_usage": {"enabled": False},
            }
        }
    )

    assert config.alerts.history_limit == 25
    assert config.alerts.cpu.warning == 70
    assert config.alerts.cpu.critical == 80
    assert config.alerts.cpu.duration == 15
    assert config.alerts.cpu.cooldown == 60
    assert config.alerts.gpu_usage.enabled is False
    assert config.alerts.disk.warning == 80


@pytest.mark.parametrize(
    "alerts",
    [
        "enabled",
        {"enabled": "true"},
        {"history_limit": 0},
        {"cpu": False},
        {"cpu": {"warning": "high"}},
        {"cpu": {"warning": 80, "critical": 80}},
        {"cpu": {"duration": -1}},
        {"cpu": {"cooldown": -1}},
        {"cpu": {"hysteresis": -1}},
        {"cpu": {"warning": 5, "hysteresis": 5}},
        {"unsupported": {"warning": 50}},
        {"cpu": {"unsupported": 1}},
    ],
)
def test_invalid_alert_configuration_is_rejected(alerts):
    with pytest.raises(ConfigError):
        AppConfig.from_mapping({"alerts": alerts})


def test_no_discovered_config_uses_typed_defaults(monkeypatch, tmp_path):
    user_path = tmp_path / "user" / "config.json"
    monkeypatch.setattr(paths, "user_config_path", lambda: user_path)

    loaded = load_config(cwd=tmp_path, environ={})

    assert loaded.config == DEFAULT_CONFIG
    assert loaded.resolution.path == user_path.resolve()
    assert loaded.resolution.source == "defaults"


def test_missing_explicit_config_is_an_error(tmp_path):
    path = tmp_path / "missing.json"

    with pytest.raises(ConfigError, match="Configuration file not found"):
        load_config(path)


def test_valid_explicit_config_is_loaded_and_deep_merged(tmp_path):
    path = _write_json(
        tmp_path / "settings.json",
        {
            "thresholds": {"cpu_warning": 55},
            "monitor": {"refresh_interval": 5},
            "logging": {"csv_path": "custom.csv"},
            "processes": {"limit": 12},
        },
    )

    loaded = load_config(path)

    assert loaded.resolution.source == "explicit"
    assert loaded.config.thresholds.cpu.warning == 55
    assert loaded.config.thresholds.cpu.critical == 80
    assert loaded.config.monitor.refresh_interval == 5
    assert loaded.config.monitor.cpu_sample_interval == 0.2
    assert loaded.config.logging.csv_path == "custom.csv"
    assert loaded.config.processes.limit == 12
    assert loaded.config.processes.sample_interval == 1.0


def test_explicit_config_wins_over_environment_and_legacy(tmp_path):
    explicit = _write_json(tmp_path / "explicit.json", {"processes": {"limit": 11}})
    environment = _write_json(tmp_path / "environment.json", {"processes": {"limit": 12}})
    _write_json(tmp_path / "config.json", {"processes": {"limit": 13}})

    loaded = load_config(
        explicit,
        environ={paths.CONFIG_ENV_VAR: str(environment)},
        cwd=tmp_path,
    )

    assert loaded.config.processes.limit == 11
    assert loaded.resolution.source == "explicit"


def test_environment_config_wins_over_legacy(tmp_path):
    environment = _write_json(tmp_path / "environment.json", {"processes": {"limit": 12}})
    _write_json(tmp_path / "config.json", {"processes": {"limit": 13}})

    loaded = load_config(
        environ={paths.CONFIG_ENV_VAR: str(environment)},
        cwd=tmp_path,
    )

    assert loaded.config.processes.limit == 12
    assert loaded.resolution.source == "environment"


def test_legacy_local_config_remains_compatible(monkeypatch, tmp_path):
    legacy = _write_json(tmp_path / "config.json", {"processes": {"limit": 13}})
    monkeypatch.setattr(paths, "user_config_path", lambda: tmp_path / "user.json")

    loaded = load_config(environ={}, cwd=tmp_path)

    assert loaded.config.processes.limit == 13
    assert loaded.resolution.path == legacy.resolve()
    assert loaded.resolution.source == "legacy"


def test_user_config_is_used_after_legacy_location(monkeypatch, tmp_path):
    user = _write_json(tmp_path / "user" / "config.json", {"processes": {"limit": 14}})
    monkeypatch.setattr(paths, "user_config_path", lambda: user)

    loaded = load_config(environ={}, cwd=tmp_path)

    assert loaded.config.processes.limit == 14
    assert loaded.resolution.source == "user"


def test_invalid_json_reports_file_and_location(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"monitor": {', encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    message = str(error.value)
    assert str(path) in message
    assert "invalid JSON" in message
    assert "line 1" in message
    assert "column" in message


def test_non_object_json_is_rejected(tmp_path):
    path = _write_json(tmp_path / "list.json", [])

    with pytest.raises(ConfigError, match="must contain a JSON object"):
        load_config(path)


@pytest.mark.parametrize(
    "raw",
    [
        {"monitor": "fast"},
        {"monitor": {"refresh_interval": "fast"}},
        {"processes": {"limit": 2.5}},
        {"processes": {"limit": True}},
        {"temperature": {"preferred_sensors": "coretemp"}},
        {"temperature": {"preferred_sensors": ["coretemp", 5]}},
        {"logging": {"csv_path": ""}},
    ],
)
def test_invalid_types_and_nested_structures_are_rejected(tmp_path, raw):
    path = _write_json(tmp_path / "invalid.json", raw)

    with pytest.raises(ConfigError, match="Invalid configuration"):
        load_config(path)


@pytest.mark.parametrize("value", [-1, 101])
def test_threshold_percentages_must_be_between_zero_and_one_hundred(tmp_path, value):
    path = _write_json(
        tmp_path / "invalid.json",
        {"thresholds": {"cpu_warning": value}},
    )

    with pytest.raises(ConfigError, match="between 0 and 100"):
        load_config(path)


@pytest.mark.parametrize("warning", [80, 90])
def test_warning_threshold_must_be_lower_than_critical(tmp_path, warning):
    path = _write_json(
        tmp_path / "invalid.json",
        {"thresholds": {"cpu_warning": warning, "cpu_critical": 80}},
    )

    with pytest.raises(ConfigError, match="lower than critical"):
        load_config(path)


@pytest.mark.parametrize(
    "raw",
    [
        {"monitor": {"refresh_interval": 0}},
        {"monitor": {"refresh_interval": -1}},
        {"monitor": {"cpu_sample_interval": -0.1}},
        {"processes": {"limit": 0}},
        {"processes": {"sample_interval": 0}},
    ],
)
def test_invalid_intervals_and_limits_are_rejected(tmp_path, raw):
    path = _write_json(tmp_path / "invalid.json", raw)

    with pytest.raises(ConfigError, match="Invalid configuration"):
        load_config(path)


def test_unknown_settings_are_rejected_to_prevent_silent_typos(tmp_path):
    path = _write_json(tmp_path / "invalid.json", {"future_key": {"enabled": True}})

    with pytest.raises(ConfigError, match="Unknown top-level setting"):
        load_config(path)


def test_config_init_creates_parent_directories_and_valid_defaults(tmp_path):
    path = tmp_path / "nested" / "config.json"

    returned = initialize_config(path)
    loaded = load_config(path)

    assert returned == path.resolve()
    assert loaded.config == DEFAULT_CONFIG
    assert json.loads(path.read_text(encoding="utf-8")) == DEFAULT_CONFIG.to_dict()


def test_config_init_refuses_to_overwrite_existing_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("original", encoding="utf-8")

    with pytest.raises(ConfigError, match="already exists"):
        initialize_config(path)

    assert path.read_text(encoding="utf-8") == "original"


def test_config_init_force_replaces_existing_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("original", encoding="utf-8")

    initialize_config(path, force=True)

    assert json.loads(path.read_text(encoding="utf-8")) == DEFAULT_CONFIG.to_dict()


def test_config_set_preserves_unrelated_settings(tmp_path):
    path = _write_json(
        tmp_path / "config.json",
        {
            "monitor": {"refresh_interval": 5},
            "processes": {"limit": 10},
        },
    )

    config = set_config_value(path, "cpu.warning", "70")
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert config.thresholds.cpu.warning == 70
    assert raw["thresholds"]["cpu_warning"] == 70
    assert raw["monitor"]["refresh_interval"] == 5
    assert raw["processes"]["limit"] == 10


def test_config_set_supports_string_and_list_values(tmp_path):
    path = tmp_path / "config.json"

    set_config_value(path, "logging.csv_path", "logs/readings.csv")
    config = set_config_value(
        path,
        "temperature.preferred_sensors",
        '["coretemp", "k10temp"]',
    )

    assert config.logging.csv_path == "logs/readings.csv"
    assert config.temperature.preferred_sensors == ("coretemp", "k10temp")


def test_config_set_supports_nested_alert_values(tmp_path):
    path = tmp_path / "config.json"

    set_config_value(path, "alerts.cpu.warning", "70")
    config = set_config_value(path, "alerts.cpu.enabled", "false")
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert config.alerts.cpu.warning == 70
    assert config.alerts.cpu.enabled is False
    assert raw["alerts"]["cpu"] == {"warning": 70, "enabled": False}


def test_config_set_supports_history_values(tmp_path):
    path = tmp_path / "config.json"

    set_config_value(path, "history.database", "logs/history.db")
    set_config_value(path, "history.retention_days", "14")
    config = set_config_value(path, "history.enabled", "false")
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert config.history == HistoryConfig(
        enabled=False,
        database="logs/history.db",
        retention_days=14,
    )
    assert raw["history"] == {
        "database": "logs/history.db",
        "retention_days": 14,
        "enabled": False,
    }


def test_invalid_alert_config_set_does_not_modify_file(tmp_path):
    path = _write_json(tmp_path / "config.json", {"alerts": {"cpu": {"warning": 70}}})
    original = path.read_bytes()

    with pytest.raises(ConfigError, match="Boolean"):
        set_config_value(path, "alerts.cpu.enabled", "yes")

    assert path.read_bytes() == original


def test_invalid_config_set_does_not_modify_existing_file(tmp_path):
    path = _write_json(tmp_path / "config.json", {"processes": {"limit": 10}})
    original = path.read_bytes()

    with pytest.raises(ConfigError, match="greater than zero"):
        set_config_value(path, "processes.limit", "0")

    assert path.read_bytes() == original


def test_unsupported_config_set_does_not_create_file(tmp_path):
    path = tmp_path / "config.json"

    with pytest.raises(ConfigError, match="Unsupported setting"):
        set_config_value(path, "unknown.value", "1")

    assert not path.exists()


def test_config_writes_use_atomic_replacement(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    replace_calls = []
    real_replace = os.replace

    def replace(source, destination):
        replace_calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(config_module.os, "replace", replace)

    initialize_config(path)

    assert len(replace_calls) == 1
    temporary, destination = replace_calls[0]
    assert Path(temporary).parent == path.parent
    assert Path(destination) == path.resolve()
    assert not Path(temporary).exists()


def test_prometheus_defaults_are_local_only_and_typed():
    prometheus = AppConfig().prometheus

    assert prometheus == PrometheusConfig(host="127.0.0.1", port=9100, interval=5.0)
    assert DEFAULT_CONFIG.to_dict()["prometheus"] == {
        "host": "127.0.0.1",
        "port": 9100,
        "interval": 5.0,
    }


def test_partial_prometheus_configuration_deep_merges_defaults(tmp_path):
    path = _write_json(tmp_path / "config.json", {"prometheus": {"port": 9200}})

    prometheus = load_config(path).config.prometheus

    assert prometheus == PrometheusConfig(host="127.0.0.1", port=9200, interval=5.0)


@pytest.mark.parametrize("port", [True, 1.5, "9100", 0, -1, 65_536])
def test_prometheus_port_validation_rejects_invalid_values(tmp_path, port):
    path = _write_json(tmp_path / "config.json", {"prometheus": {"port": port}})

    with pytest.raises(ConfigError, match="prometheus.port"):
        load_config(path)


@pytest.mark.parametrize("interval", [True, "5", 0, -1, float("inf")])
def test_prometheus_interval_validation_rejects_invalid_values(interval):
    with pytest.raises(ConfigError, match="prometheus.interval"):
        PrometheusConfig(interval=interval)


@pytest.mark.parametrize(
    "host",
    ["", "  ", " local host", "local host", "http://localhost", "host/path", "a\\b"],
)
def test_prometheus_host_validation_rejects_malformed_values(host):
    with pytest.raises(ConfigError, match="prometheus.host"):
        PrometheusConfig(host=host)


def test_prometheus_host_validation_accepts_hostnames_ipv4_and_ipv6():
    assert PrometheusConfig(host="localhost").host == "localhost"
    assert PrometheusConfig(host="0.0.0.0").host == "0.0.0.0"
    assert PrometheusConfig(host="::1").host == "::1"


def test_unknown_prometheus_fields_are_rejected(tmp_path):
    path = _write_json(tmp_path / "config.json", {"prometheus": {"enabled": True}})

    with pytest.raises(ConfigError, match="Unknown prometheus setting"):
        load_config(path)


def test_config_set_supports_prometheus_values(tmp_path):
    path = tmp_path / "config.json"

    set_config_value(path, "prometheus.host", "0.0.0.0")
    set_config_value(path, "prometheus.port", "9200")
    config = set_config_value(path, "prometheus.interval", "2")

    assert config.prometheus == PrometheusConfig(host="0.0.0.0", port=9200, interval=2.0)
