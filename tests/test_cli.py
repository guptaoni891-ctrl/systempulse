from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import psutil
import pytest

import systempulse.cli as cli
from systempulse import __version__
from systempulse.config import (
    AppConfig,
    ConfigError,
    HistoryConfig,
    LoadedConfig,
    PrometheusConfig,
)
from systempulse.exporter import PrometheusDependencyError
from systempulse.history import HistoryError
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


def _mock_monitor_service(monkeypatch, config, *, snapshot=None):
    service = Mock()
    service.config = config
    service.sample.return_value = snapshot or object()
    constructor = Mock(return_value=service)
    monkeypatch.setattr(cli, "MonitorService", constructor)
    return service, constructor


def test_build_parser_supports_existing_commands_and_global_options():
    parser = cli.build_parser()

    assert parser.prog == "systempulse"
    assert parser.description == "Cross-platform system monitoring from the terminal."
    assert parser.parse_args([]).command is None
    assert parser.parse_args(["snapshot"]).command == "snapshot"
    assert parser.parse_args(["live"]).command == "live"
    assert parser.parse_args(["alerts"]).command == "alerts"
    assert parser.parse_args(["alerts", "--history", "--limit", "5"]).history is True
    history = parser.parse_args(["history", "--hours", "24", "--limit", "5"])
    assert history.hours == 24
    assert history.days is None
    assert history.limit == 5
    assert parser.parse_args(["processes", "--limit", "10"]).limit == 10
    assert parser.parse_args(["network", "--speed"]).speed is True
    assert parser.parse_args(["save", "--output", "custom.csv"]).output == "custom.csv"
    serve = parser.parse_args(
        ["serve", "--host", "localhost", "--port", "9200", "--interval", "2.5"]
    )
    assert (serve.host, serve.port, serve.interval) == ("localhost", 9200, 2.5)
    assert parser.parse_args(["show-config"]).command == "show-config"
    assert parser.parse_args(["config", "show"]).config_command == "show"


def test_no_command_dispatches_to_interactive_menu(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    service, constructor = _mock_monitor_service(monkeypatch, config)
    menu = Mock()
    history_store = Mock()
    prepare_history = Mock(return_value=(history_store, None))
    monkeypatch.setattr(cli, "interactive_menu", menu)
    monkeypatch.setattr(cli, "_prepare_history", prepare_history)

    result = cli.main([])

    assert result == 0
    constructor.assert_called_once_with(config, include_gpu=True)
    prepare_history.assert_called_once_with(config)
    menu.assert_called_once_with(
        service,
        history_store=history_store,
        history_warning=None,
    )


def test_interactive_menu_dispatches_each_existing_choice_once(monkeypatch):
    config = AppConfig()
    snapshot = object()
    service = Mock(config=config)
    service.sample.return_value = snapshot
    history_store = Mock()
    processes = [object()]
    monkeypatch.setattr(
        cli.Prompt,
        "ask",
        Mock(side_effect=["1", "2", "3", "4", "5", "6", "7", "8"]),
    )
    monkeypatch.setattr(cli.console, "print", Mock())
    monkeypatch.setattr(cli, "print_snapshot", Mock())
    monkeypatch.setattr(cli, "live_monitor", Mock())
    monkeypatch.setattr(cli, "get_top_processes", Mock(return_value=processes))
    monkeypatch.setattr(cli, "print_processes", Mock())
    monkeypatch.setattr(cli, "_show_network", Mock())
    monkeypatch.setattr(cli, "_save", Mock())
    monkeypatch.setattr(cli, "_print_config", Mock())

    cli.interactive_menu(
        service,
        history_store=history_store,
        history_warning="history unavailable",
    )

    cli.print_snapshot.assert_called_once_with(snapshot, config)
    cli.live_monitor.assert_called_once_with(
        service,
        history_store=history_store,
        history_warning="history unavailable",
    )
    cli.get_top_processes.assert_called_once_with(limit=5, sample_interval=1.0)
    cli.print_processes.assert_called_once_with(processes)
    assert cli._show_network.mock_calls == [call(service, False), call(service, True)]
    cli._save.assert_called_once_with(service)
    cli._print_config.assert_called_once_with(config)


def test_snapshot_dispatches_collected_snapshot(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    snapshot = object()
    service, constructor = _mock_monitor_service(monkeypatch, config, snapshot=snapshot)
    print_snapshot = Mock()
    monkeypatch.setattr(cli, "print_snapshot", print_snapshot)

    assert cli.main(["snapshot"]) == 0

    constructor.assert_called_once_with(config, include_gpu=True)
    service.sample.assert_called_once_with()
    print_snapshot.assert_called_once_with(snapshot, config)


def test_live_dispatches_without_starting_real_monitor(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    service, constructor = _mock_monitor_service(monkeypatch, config)
    live_monitor = Mock()
    history_store = Mock()
    prepare_history = Mock(return_value=(history_store, None))
    monkeypatch.setattr(cli, "live_monitor", live_monitor)
    monkeypatch.setattr(cli, "_prepare_history", prepare_history)

    assert cli.main(["live"]) == 0

    constructor.assert_called_once_with(config, include_gpu=True)
    prepare_history.assert_called_once_with(config)
    live_monitor.assert_called_once_with(
        service,
        history_store=history_store,
        history_warning=None,
    )


def test_alerts_command_reports_rules_without_claiming_persistent_state(monkeypatch):
    _mock_loaded_config(monkeypatch)
    output = Mock()
    print_json = Mock()
    monkeypatch.setattr(cli.console, "print", output)
    monkeypatch.setattr(cli.console, "print_json", print_json)

    assert cli.main(["alerts"]) == 0

    assert "process-local" in output.call_args.args[0]
    assert '"history_limit": 100' in print_json.call_args.args[0]


def test_alerts_history_reads_persisted_events(monkeypatch, tmp_path):
    config = AppConfig(history=HistoryConfig(database=str(tmp_path / "history.db")))
    _mock_loaded_config(monkeypatch, config)
    events = (object(),)
    store = Mock(path=tmp_path / "history.db")
    store.recent_alert_events.return_value = events
    monkeypatch.setattr(cli, "HistoryStore", Mock(return_value=store))
    output = Mock()
    monkeypatch.setattr(cli, "print_alert_history", output)

    assert cli.main(["alerts", "--history", "--limit", "7"]) == 0

    store.recent_alert_events.assert_called_once_with(limit=7)
    output.assert_called_once_with(events, str(store.path))


def test_history_command_queries_summary_and_recent_samples(monkeypatch, tmp_path):
    config = AppConfig(history=HistoryConfig(database=str(tmp_path / "history.db")))
    _mock_loaded_config(monkeypatch, config)
    since = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    summary = object()
    samples = (object(),)
    store = Mock(path=tmp_path / "history.db")
    store.query_summary.return_value = summary
    store.recent_samples.return_value = samples
    monkeypatch.setattr(cli, "HistoryStore", Mock(return_value=store))
    monkeypatch.setattr(cli, "_history_since", Mock(return_value=since))
    output = Mock()
    monkeypatch.setattr(cli, "print_history", output)

    assert cli.main(["history", "--days", "7", "--limit", "5"]) == 0

    cli._history_since.assert_called_once_with(hours=None, days=7)
    store.query_summary.assert_called_once_with(since=since)
    store.recent_samples.assert_called_once_with(since=since, limit=5)
    output.assert_called_once_with(summary, samples, str(store.path))


def test_history_time_filters_use_aware_utc_clock():
    now = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)

    assert cli._history_since(hours=24, days=None, now=now) == now - timedelta(hours=24)
    assert cli._history_since(hours=None, days=7, now=now) == now - timedelta(days=7)
    assert cli._history_since(hours=None, days=None, now=now) is None


def test_disabled_history_commands_do_not_open_database(monkeypatch):
    config = AppConfig(history=HistoryConfig(enabled=False))
    _mock_loaded_config(monkeypatch, config)
    constructor = Mock()
    output = Mock()
    monkeypatch.setattr(cli, "HistoryStore", constructor)
    monkeypatch.setattr(cli.console, "print", output)

    assert cli.main(["history"]) == 0
    assert cli.main(["alerts", "--history"]) == 0

    constructor.assert_not_called()
    assert output.call_count == 2


def test_prepare_history_initializes_custom_path_and_cleans_up_once(monkeypatch, tmp_path):
    config = AppConfig(
        history=HistoryConfig(database=str(tmp_path / "custom.db"), retention_days=14)
    )
    store = Mock()
    constructor = Mock(return_value=store)
    monkeypatch.setattr(cli, "HistoryStore", constructor)

    returned, warning = cli._prepare_history(config)

    assert returned is store
    assert warning is None
    constructor.assert_called_once_with(str(tmp_path / "custom.db"))
    store.cleanup.assert_called_once_with(14)


def test_prepare_history_returns_one_controlled_warning_on_failure(monkeypatch, tmp_path):
    config = AppConfig(history=HistoryConfig(database=str(tmp_path / "broken.db")))
    monkeypatch.setattr(
        cli,
        "HistoryStore",
        Mock(side_effect=HistoryError("database unavailable")),
    )

    store, warning = cli._prepare_history(config)

    assert store is None
    assert warning == "database unavailable"


def test_history_error_has_stable_exit_code(monkeypatch):
    _mock_loaded_config(monkeypatch)
    monkeypatch.setattr(
        cli,
        "HistoryStore",
        Mock(side_effect=HistoryError("corrupt database")),
    )
    output = Mock()
    monkeypatch.setattr(cli.console, "print", output)

    assert cli.main(["history"]) == 3
    assert "History error" in output.call_args.args[0]


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
    config, _ = _mock_loaded_config(monkeypatch)
    service, constructor = _mock_monitor_service(monkeypatch, config)
    show_network = Mock()
    monkeypatch.setattr(cli, "_show_network", show_network)

    assert cli.main(arguments) == 0

    constructor.assert_called_once_with(config, include_gpu=False)
    show_network.assert_called_once_with(service, speed)


def test_save_dispatches_with_output_override(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    service, constructor = _mock_monitor_service(monkeypatch, config)
    save = Mock()
    monkeypatch.setattr(cli, "_save", save)

    assert cli.main(["save", "--output", "logs/custom.csv"]) == 0

    constructor.assert_called_once_with(config, include_gpu=True)
    save.assert_called_once_with(service, "logs/custom.csv")


def test_network_totals_are_formatted_without_host_network_access(monkeypatch):
    service = Mock()
    service.sample.return_value = SimpleNamespace(
        network=NetworkStats(bytes_sent=1_024, bytes_received=2_048)
    )
    print_output = Mock()
    monkeypatch.setattr(cli.console, "print", print_output)

    cli._show_network(service, False)

    service.sample.assert_called_once_with()
    assert print_output.mock_calls == [
        call("Sent since boot:     1.00 KiB"),
        call("Received since boot: 2.00 KiB"),
    ]


def test_network_speed_is_formatted_without_sleeping(monkeypatch):
    service = Mock()
    service.sample_with_network_rate.return_value = SimpleNamespace(
        network_speed=NetworkSpeed(1_024.0, 2_048.0)
    )
    print_output = Mock()
    monkeypatch.setattr(cli.console, "print", print_output)

    cli._show_network(service, True)

    service.sample_with_network_rate.assert_called_once_with()
    assert print_output.mock_calls == [
        call("Upload:   1.00 KiB/s"),
        call("Download: 2.00 KiB/s"),
    ]


def test_save_uses_one_authoritative_sample_and_configured_csv_path(monkeypatch):
    config = _config()
    snapshot = object()
    service = Mock()
    service.config = config
    service.sample_with_network_rate.return_value = snapshot
    save_snapshot = Mock(return_value=Path("system_log.csv"))
    monkeypatch.setattr(cli, "save_snapshot", save_snapshot)
    monkeypatch.setattr(cli.console, "print", Mock())

    cli._save(service)

    service.sample_with_network_rate.assert_called_once_with()
    save_snapshot.assert_called_once_with(snapshot, "system_log.csv")


def test_show_config_legacy_alias_prints_effective_configuration(monkeypatch):
    _mock_loaded_config(monkeypatch)
    print_json = Mock()
    monkeypatch.setattr(cli.console, "print_json", print_json)

    assert cli.main(["show-config"]) == 0

    assert '"csv_path": "system_log.csv"' in print_json.call_args.args[0]


def test_explicit_config_path_is_passed_to_loader(monkeypatch, tmp_path):
    config, load_config = _mock_loaded_config(monkeypatch)
    _mock_monitor_service(monkeypatch, config)
    monkeypatch.setattr(cli, "print_snapshot", Mock())
    config_path = tmp_path / "settings.json"

    assert cli.main(["--config", str(config_path), "snapshot"]) == 0

    load_config.assert_called_once_with(str(config_path))


def test_no_gpu_is_forwarded_to_monitor_service(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    service, constructor = _mock_monitor_service(monkeypatch, config)
    monkeypatch.setattr(cli, "print_snapshot", Mock())

    assert cli.main(["--no-gpu", "snapshot"]) == 0

    constructor.assert_called_once_with(config, include_gpu=False)
    service.sample.assert_called_once_with()


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


def test_config_set_forwards_nested_alert_setting(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    resolution = ConfigPath(path, "user", True)
    monkeypatch.setattr(cli, "resolve_config_path", Mock(return_value=resolution))
    set_value = Mock(return_value=AppConfig())
    monkeypatch.setattr(cli, "set_config_value", set_value)
    monkeypatch.setattr(cli.console, "print", Mock())

    assert cli.main(["config", "set", "alerts.cpu.warning", "70"]) == 0

    set_value.assert_called_once_with(path, "alerts.cpu.warning", "70")


def test_config_set_forwards_history_setting(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    resolution = ConfigPath(path, "user", True)
    monkeypatch.setattr(cli, "resolve_config_path", Mock(return_value=resolution))
    set_value = Mock(return_value=AppConfig())
    monkeypatch.setattr(cli, "set_config_value", set_value)
    monkeypatch.setattr(cli.console, "print", Mock())

    assert cli.main(["config", "set", "history.retention_days", "14"]) == 0

    set_value.assert_called_once_with(path, "history.retention_days", "14")


def test_configuration_error_has_stable_exit_code(monkeypatch):
    monkeypatch.setattr(cli, "load_config", Mock(side_effect=ConfigError("bad config")))
    output = Mock()
    monkeypatch.setattr(cli.console, "print", output)

    assert cli.main(["snapshot"]) == 2

    assert "Configuration error" in output.call_args.args[0]


def test_expected_operational_error_has_stable_exit_code(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    service, _ = _mock_monitor_service(monkeypatch, config)
    service.sample.side_effect = OSError("unavailable")
    output = Mock()
    monkeypatch.setattr(cli.console, "print", output)

    assert cli.main(["snapshot"]) == 1

    assert "SystemPulse error" in output.call_args.args[0]


def test_expected_psutil_error_has_stable_exit_code(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    service, _ = _mock_monitor_service(monkeypatch, config)
    service.sample.side_effect = psutil.AccessDenied(10)
    monkeypatch.setattr(cli.console, "print", Mock())

    assert cli.main(["snapshot"]) == 1


def test_keyboard_interrupt_has_conventional_exit_code(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    _mock_monitor_service(monkeypatch, config)
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


def test_serve_uses_prometheus_config_and_monitor_service(monkeypatch):
    config = AppConfig(prometheus=PrometheusConfig(host="localhost", port=9200, interval=3.0))
    _mock_loaded_config(monkeypatch, config)
    service, constructor = _mock_monitor_service(monkeypatch, config)
    serve = Mock()
    monkeypatch.setattr(cli, "serve_exporter", serve)

    assert cli.main(["serve"]) == 0

    constructor.assert_called_once_with(config, include_gpu=True)
    serve.assert_called_once_with(service, host="localhost", port=9200, interval=3.0)


def test_serve_cli_values_override_prometheus_config(monkeypatch):
    config = AppConfig(prometheus=PrometheusConfig(host="config-host", port=9200, interval=3.0))
    _mock_loaded_config(monkeypatch, config)
    service, _ = _mock_monitor_service(monkeypatch, config)
    serve = Mock()
    monkeypatch.setattr(cli, "serve_exporter", serve)

    assert (
        cli.main(["--no-gpu", "serve", "--host", "127.0.0.2", "--port", "9300", "--interval", "1"])
        == 0
    )

    serve.assert_called_once_with(service, host="127.0.0.2", port=9300, interval=1.0)
    cli.MonitorService.assert_called_once_with(config, include_gpu=False)


@pytest.mark.parametrize(
    "arguments",
    [
        ["serve", "--port", "0"],
        ["serve", "--port", "65536"],
        ["serve", "--interval", "0"],
        ["serve", "--interval", "nan"],
        ["serve", "--host", "http://localhost"],
    ],
)
def test_serve_rejects_invalid_cli_values(arguments):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2


def test_missing_prometheus_extra_is_an_actionable_operational_error(monkeypatch):
    config, _ = _mock_loaded_config(monkeypatch)
    _mock_monitor_service(monkeypatch, config)
    monkeypatch.setattr(
        cli,
        "serve_exporter",
        Mock(side_effect=PrometheusDependencyError('install "systempulse[prometheus]"')),
    )
    output = Mock()
    monkeypatch.setattr(cli.console, "print", output)

    assert cli.main(["serve"]) == 1
    message = output.call_args.args[0]
    assert "Prometheus exporter error" in message
    assert "systempulse\\[prometheus]" in message


def test_prometheus_extra_hint_survives_rich_markup(capsys):
    cli.console.print(
        f"[bold red]Prometheus exporter error:[/bold red] "
        f"{cli.escape('Install systempulse[prometheus].')}"
    )

    assert "systempulse[prometheus]" in capsys.readouterr().out
