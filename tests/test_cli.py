from pathlib import Path
from unittest.mock import Mock, call

import psutil
import pytest

import systempulse.cli as cli
from systempulse import __version__
from systempulse.config import AppConfig, ConfigError, LoadedConfig
from systempulse.models import NetworkSpeed, NetworkStats
from systempulse.paths import ConfigPath


def _config() -> AppConfig:
    return AppConfig()


def _mock_loaded_config(monkeypatch, config=None):
    loaded_config = config or _config()
    loaded = LoadedConfig(
        config=loaded_config,
        resolution=ConfigPath(Path("config.json"), "legacy", True),
    )
    load_config = Mock(return_value=loaded)
    monkeypatch.setattr(cli, "load_config", load_config)
    return loaded_config, load_config


def test_build_parser_supports_existing_commands_and_global_options():
    parser = cli.build_parser()

    assert parser.prog == "systempulse"
    assert parser.description == "Cross-platform system monitoring from the terminal."
    assert parser.parse_args([]).command is None
    assert parser.parse_args(["snapshot"]).command == "snapshot"
    assert parser.parse_args(["live"]).command == "live"
    assert parser.parse_args(["processes", "--limit", "10"]).limit == 10
    assert parser.parse_args(["network", "--speed"]).speed is True
    assert parser.parse_args(["save", "--output", "custom.csv"]).output == "custom.csv"
    assert parser.parse_args(["show-config"]).command == "show-config"
    assert parser.parse_args(["config", "show"]).config_command == "show"


def test_no_command_dispatches_to_interactive_menu(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    menu = Mock()
    monkeypatch.setattr(cli, "interactive_menu", menu)

    result = cli.main([])

    assert result == 0
    menu.assert_called_once_with(config, True)


def test_snapshot_dispatches_collected_snapshot(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    snapshot = object()
    collect = Mock(return_value=snapshot)
    print_snapshot = Mock()
    monkeypatch.setattr(cli, "collect_system_snapshot", collect)
    monkeypatch.setattr(cli, "print_snapshot", print_snapshot)

    assert cli.main(["snapshot"]) == 0

    collect.assert_called_once_with(config, include_gpu=True)
    print_snapshot.assert_called_once_with(snapshot, config)


def test_live_dispatches_without_starting_real_monitor(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    live_monitor = Mock()
    monkeypatch.setattr(cli, "live_monitor", live_monitor)

    assert cli.main(["live"]) == 0

    live_monitor.assert_called_once_with(config, include_gpu=True)


def test_processes_uses_cli_limit_and_configured_sample_interval(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    processes = [object()]
    get_top_processes = Mock(return_value=processes)
    print_processes = Mock()
    monkeypatch.setattr(cli, "get_top_processes", get_top_processes)
    monkeypatch.setattr(cli, "print_processes", print_processes)

    assert cli.main(["processes", "--limit", "8"]) == 0

    get_top_processes.assert_called_once_with(limit=8, sample_interval=1.0)
    print_processes.assert_called_once_with(processes)
    assert config.processes.limit == 5


@pytest.mark.parametrize(
    ("arguments", "speed"),
    [(["network"], False), (["network", "--speed"], True)],
)
def test_network_dispatches_current_mode(monkeypatch, arguments, speed):
    _mock_loaded_config(monkeypatch)
    show_network = Mock()
    monkeypatch.setattr(cli, "_show_network", show_network)

    assert cli.main(arguments) == 0

    show_network.assert_called_once_with(speed)


def test_save_dispatches_with_output_override(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    save = Mock()
    monkeypatch.setattr(cli, "_save", save)

    assert cli.main(["save", "--output", "logs/custom.csv"]) == 0

    save.assert_called_once_with(config, True, "logs/custom.csv")


def test_network_totals_are_formatted_without_host_network_access(monkeypatch):
    get_totals = Mock(return_value=NetworkStats(bytes_sent=1_024, bytes_received=2_048))
    print_output = Mock()
    monkeypatch.setattr(cli, "get_network_totals", get_totals)
    monkeypatch.setattr(cli.console, "print", print_output)

    cli._show_network(False)

    get_totals.assert_called_once_with()
    assert print_output.mock_calls == [
        call("Sent since boot:     1.00 KiB"),
        call("Received since boot: 2.00 KiB"),
    ]


def test_network_speed_is_formatted_without_sleeping(monkeypatch):
    measure = Mock(return_value=NetworkSpeed(1_024.0, 2_048.0))
    print_output = Mock()
    monkeypatch.setattr(cli, "measure_network_speed", measure)
    monkeypatch.setattr(cli.console, "print", print_output)

    cli._show_network(True)

    measure.assert_called_once_with()
    assert print_output.mock_calls == [
        call("Upload:   1.00 KiB/s"),
        call("Download: 2.00 KiB/s"),
    ]


def test_save_uses_one_measured_speed_and_configured_csv_path(monkeypatch):
    config = _config()
    speed = NetworkSpeed(10.0, 20.0)
    snapshot = object()
    measure = Mock(return_value=speed)
    collect = Mock(return_value=snapshot)
    save_snapshot = Mock(return_value=Path("system_log.csv"))
    monkeypatch.setattr(cli, "measure_network_speed", measure)
    monkeypatch.setattr(cli, "collect_system_snapshot", collect)
    monkeypatch.setattr(cli, "save_snapshot", save_snapshot)
    monkeypatch.setattr(cli.console, "print", Mock())

    cli._save(config, include_gpu=False)

    measure.assert_called_once_with()
    collect.assert_called_once_with(config, include_gpu=False)
    save_snapshot.assert_called_once_with(snapshot, speed, "system_log.csv")


def test_show_config_legacy_alias_prints_effective_configuration(monkeypatch):
    _mock_loaded_config(monkeypatch)
    print_json = Mock()
    monkeypatch.setattr(cli.console, "print_json", print_json)

    assert cli.main(["show-config"]) == 0

    assert '"csv_path": "system_log.csv"' in print_json.call_args.args[0]


def test_explicit_config_path_is_passed_to_loader(monkeypatch, tmp_path):
    _, load_config = _mock_loaded_config(monkeypatch)
    monkeypatch.setattr(cli, "collect_system_snapshot", Mock(return_value=object()))
    monkeypatch.setattr(cli, "print_snapshot", Mock())
    config_path = tmp_path / "settings.json"

    assert cli.main(["--config", str(config_path), "snapshot"]) == 0

    load_config.assert_called_once_with(str(config_path))


def test_no_gpu_is_forwarded_to_snapshot_collection(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    collect = Mock(return_value=object())
    monkeypatch.setattr(cli, "collect_system_snapshot", collect)
    monkeypatch.setattr(cli, "print_snapshot", Mock())

    assert cli.main(["--no-gpu", "snapshot"]) == 0

    collect.assert_called_once_with(config, include_gpu=False)


def test_config_show_uses_effective_config(monkeypatch):
    _mock_loaded_config(monkeypatch)
    print_json = Mock()
    monkeypatch.setattr(cli.console, "print_json", print_json)

    assert cli.main(["config", "show"]) == 0

    assert '"cpu_warning": 60.0' in print_json.call_args.args[0]


def test_config_path_prints_resolved_path(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    resolution = ConfigPath(path, "defaults", False)
    monkeypatch.setattr(cli, "resolve_config_path", Mock(return_value=resolution))
    output = Mock()
    monkeypatch.setattr(cli.console, "print", output)

    assert cli.main(["config", "path"]) == 0

    output.assert_called_once_with(str(path))


def test_config_init_uses_user_path_and_refuses_overwrite_by_default(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    initialize = Mock(return_value=path)
    monkeypatch.setattr(cli, "user_config_path", Mock(return_value=path))
    monkeypatch.setattr(cli, "initialize_config", initialize)
    monkeypatch.setattr(cli.console, "print", Mock())

    assert cli.main(["config", "init"]) == 0

    initialize.assert_called_once_with(path, force=False)


def test_config_set_updates_active_path(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    resolution = ConfigPath(path, "user", True)
    monkeypatch.setattr(cli, "resolve_config_path", Mock(return_value=resolution))
    set_value = Mock(return_value=AppConfig())
    monkeypatch.setattr(cli, "set_config_value", set_value)
    monkeypatch.setattr(cli.console, "print", Mock())

    assert cli.main(["config", "set", "cpu.warning", "70"]) == 0

    set_value.assert_called_once_with(path, "cpu.warning", "70")


def test_configuration_error_has_stable_exit_code(monkeypatch):
    monkeypatch.setattr(cli, "load_config", Mock(side_effect=ConfigError("bad config")))
    output = Mock()
    monkeypatch.setattr(cli.console, "print", output)

    assert cli.main(["snapshot"]) == 2

    assert "Configuration error" in output.call_args.args[0]


def test_expected_operational_error_has_stable_exit_code(monkeypatch):
    _mock_loaded_config(monkeypatch)
    monkeypatch.setattr(cli, "collect_system_snapshot", Mock(side_effect=OSError("unavailable")))
    output = Mock()
    monkeypatch.setattr(cli.console, "print", output)

    assert cli.main(["snapshot"]) == 1

    assert "SystemPulse error" in output.call_args.args[0]


def test_expected_psutil_error_has_stable_exit_code(monkeypatch):
    _mock_loaded_config(monkeypatch)
    monkeypatch.setattr(
        cli,
        "collect_system_snapshot",
        Mock(side_effect=psutil.AccessDenied(10)),
    )
    monkeypatch.setattr(cli.console, "print", Mock())

    assert cli.main(["snapshot"]) == 1


def test_keyboard_interrupt_has_conventional_exit_code(monkeypatch):
    _mock_loaded_config(monkeypatch)
    monkeypatch.setattr(cli, "interactive_menu", Mock(side_effect=KeyboardInterrupt))

    assert cli.main([]) == 130


def test_help_exits_successfully_without_loading_config(monkeypatch, capsys):
    load_config = Mock()
    monkeypatch.setattr(cli, "load_config", load_config)

    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])

    assert error.value.code == 0
    assert "usage: systempulse" in capsys.readouterr().out
    load_config.assert_not_called()


def test_version_exits_successfully_without_loading_config(monkeypatch, capsys):
    load_config = Mock()
    monkeypatch.setattr(cli, "load_config", load_config)

    with pytest.raises(SystemExit) as error:
        cli.main(["--version"])

    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == f"systempulse {__version__}"
    load_config.assert_not_called()


def test_invalid_command_exits_with_argparse_error(monkeypatch, capsys):
    load_config = Mock()
    monkeypatch.setattr(cli, "load_config", load_config)

    with pytest.raises(SystemExit) as error:
        cli.main(["not-a-command"])

    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    load_config.assert_not_called()
