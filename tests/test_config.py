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
