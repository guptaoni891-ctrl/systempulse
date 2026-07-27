# SystemPulse

A Linux system monitor built with Python. It provides a polished terminal dashboard, process inspection, network measurements, temperature monitoring, optional NVIDIA GPU support, configurable thresholds, CSV history, tests, packaging, and CI.

## Why this project is portfolio-worthy

SystemPulse is more than a single-file script. It demonstrates:

- modular Python architecture
- dataclasses and type hints
- defensive error handling
- JSON configuration with defaults
- subprocess integration through `nvidia-smi`
- live terminal UI with Rich
- reusable data collection and CSV persistence
- command-line subcommands with `argparse`
- automated tests with pytest
- linting and GitHub Actions CI
- installable packaging through `pyproject.toml`

## Features

- CPU usage
- RAM usage and capacity
- disk usage and capacity
- CPU temperature detection on Linux
- total sent and received network traffic
- live upload and download speed
- top CPU-consuming processes
- NVIDIA GPU usage, temperature, VRAM, and power
- multiple NVIDIA GPU parsing
- live full-screen dashboard
- CSV logging
- configurable warning and critical thresholds
- graceful fallback when sensors, config, or `nvidia-smi` are unavailable

## Installation

```bash
cd systempulse_final
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Run the interactive menu:

```bash
systempulse
```

You can also run it without installing the command:

```bash
python -m systempulse
```

## Commands

```bash
systempulse snapshot
systempulse live
systempulse processes
systempulse processes --limit 10
systempulse network
systempulse network --speed
systempulse save
systempulse save --output logs/readings.csv
systempulse show-config
systempulse --no-gpu snapshot
systempulse --config custom-config.json live
```

## Configuration

Edit `config.json` to control:

- CPU, RAM, disk, temperature, and GPU thresholds
- dashboard refresh interval
- CPU sampling interval
- CSV output path
- number of displayed processes
- preferred Linux temperature sensor names

If the config file is missing or invalid, SystemPulse prints a warning and continues with safe defaults.

## CSV output

The logger records:

- timestamp
- CPU, RAM, and disk usage
- raw RAM and disk byte counts
- CPU temperature
- network totals and speeds
- NVIDIA GPU name, usage, temperature, VRAM, and power

The default output is `system_log.csv`.

## Tests and linting

```bash
pytest
ruff check .
```

GitHub Actions runs both checks on pushes and pull requests.

## Project structure

```text
systempulse_final/
├── .github/workflows/tests.yml
├── src/systempulse/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── collector.py
│   ├── config.py
│   ├── gpu.py
│   ├── logger.py
│   ├── models.py
│   ├── monitor.py
│   ├── network.py
│   ├── processes.py
│   ├── status.py
│   ├── ui.py
│   └── utils.py
├── tests/
├── config.json
├── pyproject.toml
├── LICENSE
└── README.md
```

## Notes

- Linux is the primary target.
- CPU temperature availability depends on the sensors exposed by the machine and kernel.
- NVIDIA metrics require a working `nvidia-smi` command.
- The application still works without NVIDIA support by using `--no-gpu` or its built-in fallback.

## Suggested GitHub polish

Before publishing:

1. Replace `Your Name` in `pyproject.toml` and `LICENSE`.
2. Rename the repository to `systempulse`.
3. Add a screenshot or short GIF of `systempulse live`.
4. Write a brief project retrospective in the README: what you learned, one difficult bug, and how you solved it.
5. Use focused commits such as `feat: add GPU metrics` and `test: cover config fallback`.
