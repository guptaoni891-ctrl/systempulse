from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
from rich.prompt import Prompt

from systempulse import __version__
from systempulse.config import (
    AppConfig,
    ConfigError,
    initialize_config,
    load_config,
    set_config_value,
)
from systempulse.history import HistoryError, HistoryStore
from systempulse.logger import save_snapshot
from systempulse.monitor import live_monitor
from systempulse.paths import resolve_config_path, user_config_path
from systempulse.processes import get_top_processes
from systempulse.service import MonitorService
from systempulse.ui import (
    console,
    print_alert_history,
    print_history,
    print_processes,
    print_snapshot,
)
from systempulse.utils import format_bytes, format_rate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="systempulse",
        description="Cross-platform system monitoring from the terminal.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Use an explicit config JSON path.",
    )
    parser.add_argument(
        "--no-gpu",
        action="store_true",
        help="Skip NVIDIA GPU detection.",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("menu", help="Open the interactive menu.")
    subparsers.add_parser("snapshot", help="Show a one-time system snapshot.")
    subparsers.add_parser("live", help="Open the live dashboard.")
    alerts_parser = subparsers.add_parser(
        "alerts",
        help="Show alert rules or persisted alert-event history.",
    )
    alerts_parser.add_argument(
        "--history",
        action="store_true",
        help="Show persisted alert transitions instead of configured rules.",
    )
    alerts_parser.add_argument(
        "--limit",
        type=_positive_cli_integer,
        default=20,
        help="Maximum persisted alert events to show (default: 20).",
    )

    history_parser = subparsers.add_parser(
        "history",
        help="Show local SQLite metric history.",
    )
    period = history_parser.add_mutually_exclusive_group()
    period.add_argument("--hours", type=_positive_cli_integer, help="Include recent hours.")
    period.add_argument("--days", type=_positive_cli_integer, help="Include recent days.")
    history_parser.add_argument(
        "--limit",
        type=_positive_cli_integer,
        default=10,
        help="Maximum recent samples to show (default: 10).",
    )

    process_parser = subparsers.add_parser("processes", help="Show top CPU processes.")
    process_parser.add_argument("--limit", type=int, help="Number of processes to show.")

    network_parser = subparsers.add_parser("network", help="Show network usage or speed.")
    network_parser.add_argument(
        "--speed",
        action="store_true",
        help="Measure upload and download speed.",
    )

    save_parser = subparsers.add_parser("save", help="Save a system snapshot to CSV.")
    save_parser.add_argument("--output", help="Override the configured CSV path.")

    subparsers.add_parser(
        "show-config",
        help="Print the effective configuration (legacy alias for 'config show').",
    )

    config_parser = subparsers.add_parser("config", help="Inspect or update configuration.")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("show", help="Print the effective configuration.")
    config_commands.add_parser("path", help="Print the active or default config path.")
    init_parser = config_commands.add_parser("init", help="Create a user configuration file.")
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing configuration file.",
    )
    set_parser = config_commands.add_parser("set", help="Set one supported configuration value.")
    set_parser.add_argument("key", help="Setting name, for example cpu.warning.")
    set_parser.add_argument("value", help="JSON value or plain string.")
    return parser


def _show_network(service: MonitorService, speed: bool) -> None:
    if speed:
        snapshot = service.sample_with_network_rate()
        console.print(f"Upload:   {format_rate(snapshot.network_speed.upload_bytes_per_second)}")
        console.print(
            f"Download: {format_rate(snapshot.network_speed.download_bytes_per_second)}"
        )
        return

    totals = service.sample().network
    console.print(f"Sent since boot:     {format_bytes(totals.bytes_sent)}")
    console.print(f"Received since boot: {format_bytes(totals.bytes_received)}")


def _save(service: MonitorService, output: str | None = None) -> None:
    snapshot = service.sample_with_network_rate()
    csv_path = output or service.config.logging.csv_path
    path = save_snapshot(snapshot, csv_path)
    console.print(f"Saved reading to [bold]{path.resolve()}[/bold]")


def _print_config(config: AppConfig) -> None:
    console.print_json(json.dumps(config.to_dict()))


def _print_alert_rules(config: AppConfig) -> None:
    console.print(
        "Active alert state is process-local and shown by [bold]systempulse live[/bold]. "
        "Use [bold]systempulse alerts --history[/bold] for persisted transitions."
    )
    console.print_json(json.dumps(config.to_dict()["alerts"]))


def _positive_cli_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def _prepare_history(config: AppConfig) -> tuple[HistoryStore | None, str | None]:
    if not config.history.enabled:
        return None, None
    try:
        store = HistoryStore(config.history.database)
        store.cleanup(config.history.retention_days)
    except HistoryError as error:
        return None, str(error)
    return store, None


def _history_since(
    *,
    hours: int | None,
    days: int | None,
    now: datetime | None = None,
) -> datetime | None:
    reference = datetime.now(UTC) if now is None else now.astimezone(UTC)
    if hours is not None:
        return reference - timedelta(hours=hours)
    if days is not None:
        return reference - timedelta(days=days)
    return None


def _show_history(config: AppConfig, args: argparse.Namespace) -> None:
    if not config.history.enabled:
        console.print("History is disabled in configuration.")
        return
    store = HistoryStore(config.history.database)
    since = _history_since(hours=args.hours, days=args.days)
    print_history(
        store.query_summary(since=since),
        store.recent_samples(since=since, limit=args.limit),
        str(store.path),
    )


def _show_alert_history(config: AppConfig, limit: int) -> None:
    if not config.history.enabled:
        console.print("History is disabled in configuration.")
        return
    store = HistoryStore(config.history.database)
    print_alert_history(store.recent_alert_events(limit=limit), str(store.path))


def interactive_menu(
    service: MonitorService,
    *,
    history_store: HistoryStore | None = None,
    history_warning: str | None = None,
) -> None:
    config = service.config
    while True:
        console.print(
            "\n[bold]SystemPulse[/bold]\n"
            "1. Show system snapshot\n"
            "2. Live monitoring\n"
            "3. Show top CPU processes\n"
            "4. Show network totals\n"
            "5. Measure network speed\n"
            "6. Save reading to CSV\n"
            "7. Show loaded config\n"
            "8. Exit"
        )
        choice = Prompt.ask("Choose", choices=[str(number) for number in range(1, 9)])

        if choice == "1":
            print_snapshot(service.sample(), config)
        elif choice == "2":
            live_monitor(
                service,
                history_store=history_store,
                history_warning=history_warning,
            )
        elif choice == "3":
            process_config = config.processes
            processes = get_top_processes(
                limit=process_config.limit,
                sample_interval=process_config.sample_interval,
            )
            print_processes(processes)
        elif choice == "4":
            _show_network(service, False)
        elif choice == "5":
            _show_network(service, True)
        elif choice == "6":
            _save(service)
        elif choice == "7":
            _print_config(config)
        else:
            return


def _handle_config_command(args: argparse.Namespace) -> int:
    if args.config_command == "path":
        resolution = resolve_config_path(args.config)
        console.print(str(resolution.path))
        return 0

    if args.config_command == "init":
        target = Path(args.config).expanduser() if args.config else user_config_path()
        path = initialize_config(target, force=args.force)
        console.print(f"Created configuration at [bold]{path}[/bold]")
        return 0

    if args.config_command == "set":
        resolution = resolve_config_path(args.config)
        set_config_value(resolution.path, args.key, args.value)
        console.print(f"Updated [bold]{args.key}[/bold] in [bold]{resolution.path}[/bold]")
        return 0

    loaded = load_config(args.config)
    _print_config(loaded.config)
    return 0


def _dispatch(args: argparse.Namespace, config: AppConfig) -> None:
    include_gpu = not args.no_gpu
    command = args.command or "menu"

    if command == "menu":
        history_store, history_warning = _prepare_history(config)
        interactive_menu(
            MonitorService(config, include_gpu=include_gpu),
            history_store=history_store,
            history_warning=history_warning,
        )
    elif command == "snapshot":
        service = MonitorService(config, include_gpu=include_gpu)
        print_snapshot(service.sample(), config)
    elif command == "live":
        history_store, history_warning = _prepare_history(config)
        live_monitor(
            MonitorService(config, include_gpu=include_gpu),
            history_store=history_store,
            history_warning=history_warning,
        )
    elif command == "alerts":
        if args.history:
            _show_alert_history(config, args.limit)
        else:
            _print_alert_rules(config)
    elif command == "history":
        _show_history(config, args)
    elif command == "processes":
        process_config = config.processes
        limit = args.limit or process_config.limit
        print_processes(
            get_top_processes(
                limit=limit,
                sample_interval=process_config.sample_interval,
            )
        )
    elif command == "network":
        _show_network(MonitorService(config, include_gpu=False), args.speed)
    elif command == "save":
        _save(MonitorService(config, include_gpu=include_gpu), args.output)
    elif command == "show-config":
        _print_config(config)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "config":
            return _handle_config_command(args)
        loaded = load_config(args.config)
        _dispatch(args, loaded.config)
    except ConfigError as error:
        console.print(f"[bold red]Configuration error:[/bold red] {error}")
        return 2
    except HistoryError as error:
        console.print(f"[bold red]History error:[/bold red] {error}")
        return 3
    except (OSError, psutil.Error) as error:
        console.print(f"[bold red]SystemPulse error:[/bold red] {error}")
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
