import json

from systempulse.config import DEFAULT_CONFIG, load_config


def test_missing_config_uses_defaults(tmp_path):
    config, warning = load_config(tmp_path / "missing.json")
    assert config == DEFAULT_CONFIG
    assert warning is not None


def test_partial_config_is_merged(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"monitor": {"refresh_interval": 5}}), encoding="utf-8")

    config, warning = load_config(path)

    assert warning is None
    assert config["monitor"]["refresh_interval"] == 5
    assert config["monitor"]["cpu_sample_interval"] == DEFAULT_CONFIG["monitor"][
        "cpu_sample_interval"
    ]


def test_valid_explicit_config_path_is_loaded(tmp_path):
    path = tmp_path / "named-settings.json"
    path.write_text(
        json.dumps(
            {
                "logging": {"csv_path": "custom.csv"},
                "processes": {"limit": 12},
            }
        ),
        encoding="utf-8",
    )

    config, warning = load_config(path)

    assert warning is None
    assert config["logging"]["csv_path"] == "custom.csv"
    assert config["processes"]["limit"] == 12
    assert config["processes"]["sample_interval"] == DEFAULT_CONFIG["processes"][
        "sample_interval"
    ]


def test_partial_nested_config_is_deep_merged_without_mutating_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "thresholds": {"cpu_warning": 55},
                "monitor": {"refresh_interval": 3.5},
            }
        ),
        encoding="utf-8",
    )

    config, warning = load_config(path)

    assert warning is None
    assert config["thresholds"]["cpu_warning"] == 55
    assert config["thresholds"]["cpu_critical"] == 80
    assert config["monitor"]["refresh_interval"] == 3.5
    assert DEFAULT_CONFIG["thresholds"]["cpu_warning"] == 60


def test_invalid_json_uses_defaults_with_location_warning(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"monitor": {', encoding="utf-8")

    config, warning = load_config(path)

    assert config == DEFAULT_CONFIG
    assert warning is not None
    assert str(path) in warning
    assert "invalid JSON" in warning
    assert "line 1" in warning
    assert "column" in warning


def test_non_object_json_uses_defaults(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")

    config, warning = load_config(path)

    assert config == DEFAULT_CONFIG
    assert warning == f"{path} must contain a JSON object; defaults are active."


def test_invalid_nested_type_is_currently_accepted_without_validation(tmp_path):
    """Document v1.1 behavior pending the future typed configuration work."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"monitor": "fast"}), encoding="utf-8")

    config, warning = load_config(path)

    assert warning is None
    assert config["monitor"] == "fast"


def test_out_of_range_values_and_unknown_keys_are_currently_preserved(tmp_path):
    """Document that v1.1 merges values but does not validate their semantics."""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "monitor": {"refresh_interval": -10},
                "thresholds": {"cpu_warning": 95, "cpu_critical": 80},
                "future_key": {"enabled": True},
            }
        ),
        encoding="utf-8",
    )

    config, warning = load_config(path)

    assert warning is None
    assert config["monitor"]["refresh_interval"] == -10
    assert config["thresholds"]["cpu_warning"] == 95
    assert config["thresholds"]["cpu_critical"] == 80
    assert config["future_key"] == {"enabled": True}
