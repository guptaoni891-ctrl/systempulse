from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rich.prompt import Prompt

from systempulse.collector import collect_system_snapshot
from systempulse.config import load_config
from systempulse.logger import save_snapshot
from systempulse.monitor import live_monitor
from systempulse.network import get_network_totals, measure_network_speed
from systempulse.processes import get_top_processes
from systempulse.ui import console, print_processes, print_snapshot, print_warning
from systempulse.utils import format_bytes, format_rate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="systempulse",
        description="Linux system monitoring from the terminal.",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON (default: config.json)",
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

    subparsers.add_parser("show-config", help="Print the merged configuration.")
    return parser


def _show_network(speed: bool) -> None:
    if speed:
        result = measure_network_speed()
        console.print(f"Upload:   {format_rate(result.upload_bytes_per_second)}")
        console.print(f"Download: {format_rate(result.download_bytes_per_second)}")
        return

    totals = get_network_totals()
    console.print(f"Sent since boot:     {format_bytes(totals.bytes_sent)}")
    console.print(f"Received since boot: {format_bytes(totals.bytes_received)}")


def _save(config: dict[str, Any], include_gpu: bool, output: str | None = None) -> None:
    speed = measure_network_speed()
    snapshot = collect_system_snapshot(config, include_gpu=include_gpu)
    csv_path = output or config["logging"]["csv_path"]
    path = save_snapshot(snapshot, speed, csv_path)
    console.print(f"Saved reading to [bold]{path.resolve()}[/bold]")


def interactive_menu(config: dict[str, Any], include_gpu: bool) -> None:
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
            snapshot = collect_system_snapshot(config, include_gpu=include_gpu)
            print_snapshot(snapshot, config)
        elif choice == "2":
            live_monitor(config, include_gpu=include_gpu)
        elif choice == "3":
            process_config = config["processes"]
            processes = get_top_processes(
                limit=process_config["limit"],
                sample_interval=process_config["sample_interval"],
            )
            print_processes(processes)
        elif choice == "4":
            _show_network(False)
        elif choice == "5":
            _show_network(True)
        elif choice == "6":
            _save(config, include_gpu)
        elif choice == "7":
            console.print_json(json.dumps(config))
        else:
            return


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config, warning = load_config(Path(args.config))
    if warning:
        print_warning(warning)

    include_gpu = not args.no_gpu
    command = args.command or "menu"

    if command == "menu":
        interactive_menu(config, include_gpu)
    elif command == "snapshot":
        print_snapshot(collect_system_snapshot(config, include_gpu=include_gpu), config)
    elif command == "live":
        live_monitor(config, include_gpu=include_gpu)
    elif command == "processes":
        process_config = config["processes"]
        limit = args.limit or process_config["limit"]
        print_processes(
            get_top_processes(
                limit=limit,
                sample_interval=process_config["sample_interval"],
            )
        )
    elif command == "network":
        _show_network(args.speed)
    elif command == "save":
        _save(config, include_gpu, args.output)
    elif command == "show-config":
        console.print_json(json.dumps(config))


if __name__ == "__main__":
    main()
