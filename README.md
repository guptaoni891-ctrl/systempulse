# SystemPulse

A modular Linux system monitor built with Python. SystemPulse provides a polished terminal dashboard for monitoring CPU, memory, disk, network, temperature, running processes, and optional NVIDIA GPU metrics.

![SystemPulse live dashboard](docs/dashboard.png)

## Features

- Real-time CPU usage
- RAM usage and capacity
- Disk usage and capacity
- Linux CPU temperature monitoring
- Network upload and download speed
- Total network traffic since boot
- Top CPU-consuming processes
- NVIDIA GPU usage, temperature, VRAM, and power
- Live terminal dashboard powered by Rich
- CSV history logging
- Configurable warning and critical thresholds
- Graceful fallbacks when sensors or `nvidia-smi` are unavailable
- Automated tests and linting
- GitHub Actions continuous integration

## Tech Stack

- Python
- psutil
- Rich
- argparse
- pytest
- Ruff
- GitHub Actions
- `nvidia-smi`

## Installation

Clone the repository:

```bash
git clone https://github.com/guptaoni891-ctrl/systempulse.git
cd systempulse
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install SystemPulse and its development dependencies:

```bash
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

Settings are stored in `config.json`.

Users can configure:

- CPU warning and critical thresholds
- RAM warning and critical thresholds
- Disk warning and critical thresholds
- CPU temperature thresholds
- GPU thresholds
- Dashboard refresh interval
- CPU sampling interval
- CSV output path
- Number of displayed processes
- Preferred Linux temperature sensor names

If the configuration file is missing or contains invalid JSON, SystemPulse continues using safe default settings.

## CSV Logging

SystemPulse can record:

- Timestamp
- CPU usage
- RAM usage and byte counts
- Disk usage and byte counts
- CPU temperature
- Network totals
- Upload and download speeds
- NVIDIA GPU name
- GPU usage
- GPU temperature
- VRAM usage
- GPU power draw

The default output file is:

```text
system_log.csv
```

## Tests and Code Quality

Run the automated tests:

```bash
python -m pytest
```

Run the linter:

```bash
python -m ruff check .
```

Current test status:

```text
11 passed
All checks passed!
```

GitHub Actions runs the tests and linting checks automatically on pushes and pull requests.

## Project Structure

```text
systempulse/
├── .github/
│   └── workflows/
│       └── tests.yml
├── docs/
│   └── dashboard.png
├── src/
│   └── systempulse/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── collector.py
│       ├── config.py
│       ├── gpu.py
│       ├── logger.py
│       ├── models.py
│       ├── monitor.py
│       ├── network.py
│       ├── processes.py
│       ├── status.py
│       ├── ui.py
│       └── utils.py
├── tests/
├── config.json
├── pyproject.toml
├── LICENSE
└── README.md
```

## Architecture

SystemPulse separates responsibilities across multiple modules:

- `collector.py` collects system metrics
- `gpu.py` handles NVIDIA GPU integration
- `network.py` measures network activity
- `processes.py` inspects running processes
- `logger.py` writes historical readings
- `ui.py` builds the terminal interface
- `config.py` loads and validates settings
- `status.py` classifies warning levels
- `cli.py` handles command-line commands

This structure keeps the project maintainable, testable, and easier to extend.

## Platform Support

Linux is the primary supported platform.

CPU temperature availability depends on the sensors exposed by the Linux kernel. NVIDIA GPU monitoring requires a working `nvidia-smi` command.

SystemPulse continues to work without NVIDIA support by using:

```bash
systempulse --no-gpu snapshot
```

## What I Learned

Building SystemPulse helped me practise:

- Designing a modular Python application
- Working with operating-system metrics
- Parsing subprocess output
- Creating reusable data models
- Building command-line interfaces
- Handling missing hardware and configuration safely
- Writing automated tests
- Packaging an installable Python project
- Using GitHub Actions for continuous integration

## License

This project is licensed under the MIT License.