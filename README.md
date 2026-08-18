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

Settings are stored in `config.json`. Users can configure CPU, RAM, disk, temperature, and GPU thresholds; refresh and CPU sampling intervals; CSV output; process count; and preferred temperature sensor names.

If the configuration file is missing or contains invalid JSON, SystemPulse continues using safe defaults.

## CPU Temperature Notes

Temperature sensor access is OS- and hardware-dependent. Linux commonly exposes CPU sensors through `psutil.sensors_temperatures()`. Windows and macOS may not expose a CPU temperature through `psutil`; in that case SystemPulse displays `Unavailable` and continues normally.

## CSV Logging

SystemPulse can record timestamp, CPU/RAM/disk usage, raw byte counts, CPU temperature when available, network totals and speeds, and NVIDIA GPU metrics when available.

The default output file is `system_log.csv`.

## Tests and Code Quality

```bash
python -m pytest
python -m ruff check .
```

GitHub Actions runs linting and tests on Windows, macOS, and Linux for Python 3.11 and 3.13.

## Architecture

SystemPulse separates responsibilities across modules: `collector.py` collects system metrics, `gpu.py` handles NVIDIA integration, `network.py` measures network activity, `processes.py` inspects running processes, `logger.py` writes CSV history, `ui.py` builds the terminal interface, `config.py` loads settings, `status.py` classifies thresholds, and `cli.py` handles commands.

## What Changed in 1.1.0

- Added Windows system-drive detection instead of assuming the Unix `/` filesystem root
- Kept `/` as the correct root on macOS and Linux
- Made missing/unsupported temperature APIs explicitly safe across platforms
- Added cross-platform collector tests
- Expanded GitHub Actions to Windows, macOS, and Linux
- Updated package metadata and documentation to describe cross-platform support accurately

## License

This project is licensed under the MIT License.
