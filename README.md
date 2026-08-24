# SystemPulse

A modular cross-platform terminal system monitor built with Python. SystemPulse provides a polished Rich dashboard for monitoring CPU, memory, disk, network, running processes, optional CPU temperature sensors, and optional NVIDIA GPU metrics on Windows, macOS, and Linux.

![SystemPulse live dashboard](docs/dashboard.png)

## Features

- Real-time CPU usage
- RAM usage and capacity
- System-disk usage and capacity
- CPU temperature when exposed by the operating system and `psutil`
- Network upload and download speed
- Total network traffic since boot
- Top CPU-consuming processes
- NVIDIA GPU usage, temperature, VRAM, and power through `nvidia-smi`
- Live terminal dashboard powered by Rich
- CSV history logging
- Configurable warning and critical thresholds
- Graceful fallbacks when temperature sensors or `nvidia-smi` are unavailable
- Automated tests and linting on Windows, macOS, and Linux

## Platform Support

| Platform | Core metrics | CPU temperature | NVIDIA GPU |
|---|---|---|---|
| Windows 10/11 | Yes | Shown when available; otherwise `Unavailable` | Yes, when `nvidia-smi` is installed |
| macOS | Yes | Shown when available; otherwise `Unavailable` | Usually unavailable on modern Macs |
| Linux | Yes | Yes when supported sensors are exposed | Yes, when `nvidia-smi` is installed |

Core monitoring—CPU, RAM, disk, network, processes, logging, and the terminal UI—works without temperature or NVIDIA support.

## Tech Stack

- Python
- psutil
- Rich
- argparse
- pytest
- Ruff
- GitHub Actions
- `nvidia-smi` (optional)

## Installation

Clone the repository:

```bash
git clone https://github.com/guptaoni891-ctrl/systempulse.git
cd systempulse
```

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Usage

Open the interactive menu:

```bash
systempulse
```

Show a single system snapshot:

```bash
systempulse snapshot
```

Start the live dashboard:

```bash
systempulse live
```

Show the top CPU-consuming processes:

```bash
systempulse processes
systempulse processes --limit 10
```

Show network statistics:

```bash
systempulse network
systempulse network --speed
```

Save a system reading to CSV:

```bash
systempulse save
systempulse save --output logs/readings.csv
```

Display the loaded configuration:

```bash
systempulse show-config
systempulse config show
```

Show the active configuration path, create a user configuration, or update a setting:

```bash
systempulse config path
systempulse config init
systempulse config set cpu.warning 70
```

`config init` refuses to replace an existing file. Use `systempulse config init --force`
only when replacement is intentional.

Show the installed version:

```bash
systempulse --version
```

Run without NVIDIA GPU monitoring:

```bash
systempulse --no-gpu snapshot
```

Use a custom configuration file:

```bash
systempulse --config custom-config.json live
```

SystemPulse can also be run without the installed command:

```bash
python -m systempulse
```

## Configuration

SystemPulse works with built-in defaults when no configuration file exists. User configuration is
stored in the platform-specific directory selected by `platformdirs`:

| Platform | Typical configuration location |
|---|---|
| Windows | `%APPDATA%\SystemPulse\config.json` |
| macOS | `~/Library/Application Support/SystemPulse/config.json` |
| Linux | `~/.config/SystemPulse/config.json` |

The exact location is available through `systempulse config path`. SystemPulse also reserves the
corresponding platform-specific user data and state directories for future persistent data.

Configuration precedence, from highest to lowest, is:

1. Explicit `--config PATH`
2. The `SYSTEMPULSE_CONFIG` environment variable
3. A legacy `config.json` in the current working directory
4. The platform-specific user configuration file
5. Built-in defaults

The legacy JSON schema remains supported. Users can configure CPU, RAM, disk, temperature, and GPU
thresholds; refresh and CPU sampling intervals; CSV output; process count; and preferred temperature
sensor names. Configuration is validated before monitoring starts, and invalid files produce a
concise configuration error instead of a runtime `KeyError` or `TypeError`.

An explicitly selected or discovered malformed file is reported as an error. A missing explicit file
is also an error; when no file is selected or discovered, built-in defaults are used silently.

## CPU Temperature Notes

Temperature sensor access is OS- and hardware-dependent. Linux commonly exposes CPU sensors through `psutil.sensors_temperatures()`. Windows and macOS may not expose a CPU temperature through `psutil`; in that case SystemPulse displays `Unavailable` and continues normally.

## CSV Logging

SystemPulse can record timestamp, CPU/RAM/disk usage, raw byte counts, CPU temperature when available, network totals and speeds, and NVIDIA GPU metrics when available.

Each row now comes from one authoritative sample. Network rates are derived from an earlier counter
reading with a monotonic clock, while the row timestamp is timezone-aware UTC.

The default output file is `system_log.csv`.

## Tests and Code Quality

```bash
python -m pytest
python -m ruff check .
```

GitHub Actions runs linting and tests on Windows, macOS, and Linux for Python 3.11 and 3.13.

## Architecture

SystemPulse separates responsibilities across modules: `collector.py` collects low-level core metrics,
`gpu.py` handles NVIDIA integration, and `service.py` combines them into the authoritative
`SystemSnapshot`. The snapshot contains timezone-aware UTC time, network totals and rates, GPU data,
and lightweight optional-collector diagnostics. `ui.py` only renders samples, `logger.py` writes a
sample to CSV, `monitor.py` schedules the live terminal display, and `cli.py` handles commands.

The live display is scheduled against monotonic target ticks. Its first sample is immediate; each
later sample starts at the configured tick. If collection runs past one or more ticks, those ticks are
skipped rather than replayed, and the next future tick remains anchored to the existing schedule.

## What Changed in 1.1.0

- Added Windows system-drive detection instead of assuming the Unix `/` filesystem root
- Kept `/` as the correct root on macOS and Linux
- Made missing/unsupported temperature APIs explicitly safe across platforms
- Added cross-platform collector tests
- Expanded GitHub Actions to Windows, macOS, and Linux
- Updated package metadata and documentation to describe cross-platform support accurately

## License

This project is licensed under the MIT License.
