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
- Local SQLite metric and alert-event history
- Optional Prometheus exporter backed by the latest in-memory sample
- Configurable warning and critical thresholds
- Stateful live alerts with duration, hysteresis, cooldown, and per-GPU rules
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

For an installed release with Prometheus exporter support:

```bash
pip install "systempulse[prometheus]"
# or
pipx install "systempulse[prometheus]"
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

Show configured alert rules and the runtime-state limitation:

```bash
systempulse alerts
systempulse alerts --history --limit 20
```

Show local metric history:

```bash
systempulse history
systempulse history --hours 24 --limit 20
systempulse history --days 7
```

Expose the latest sample at `http://127.0.0.1:9100/metrics`:

```bash
systempulse serve
systempulse serve --host 127.0.0.1 --port 9100 --interval 5
```

The default bind is local-only. Binding to `0.0.0.0` or another network interface is an explicit
choice because host metrics can reveal information about the machine. The sampling interval controls
how often SystemPulse polls the host; it is independent of Prometheus's scrape interval. Scraping
`/metrics` only reads the latest in-memory snapshot and never invokes `psutil` or `nvidia-smi`.

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
systempulse config set alerts.cpu.warning 80
systempulse config set alerts.cpu.duration 30
systempulse config set history.retention_days 14
systempulse config set history.database /custom/path/systempulse.db
systempulse config set prometheus.port 9200
systempulse config set prometheus.interval 2
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

The `alerts` section has a global `enabled` flag, a bounded `history_limit`, and rules for
`cpu`, `memory`, `disk`, `cpu_temperature`, `gpu_usage`, and `gpu_temperature`. Each rule has
`enabled`, `warning`, `critical`, `duration`, `cooldown`, and `hysteresis` settings. These alert
thresholds are intentionally separate from the legacy presentation thresholds so changing a live
alert rule does not silently alter the existing status display.

The `history` section contains `enabled`, `database`, and `retention_days`. History is enabled by
default, retains 30 days, and stores `systempulse.db` under the platform-specific SystemPulse user
data directory selected by `platformdirs`. A custom database path may be absolute or relative to the
process working directory. Retention must be a positive number of days.

The `prometheus` section contains `host`, `port`, and `interval`, defaulting to `127.0.0.1`, `9100`,
and 5 seconds. `systempulse serve --host/--port/--interval` overrides the corresponding loaded
configuration for that invocation. Configuration-file precedence remains as listed above; command
options are the final exporter-only override. Host validation is local and performs no DNS lookup.

An explicitly selected or discovered malformed file is reported as an error. A missing explicit file
is also an error; when no file is selected or discovered, built-in defaults are used silently.

## Prometheus Exporter

SystemPulse exports numeric base units with the `systempulse_` prefix. CPU, memory, disk, and GPU
usage percentages are converted at the exporter boundary into ratios from 0 to 1. Memory and disk
capacities use bytes, rates use bytes per second, temperatures use Celsius, power uses watts, and
timestamps use Unix seconds. Raw network totals are exposed as counters so Prometheus can recognize
an operating-system counter reset; SystemPulse's calculated network rates remain gauges.

Multiple GPUs share metric names and use only a bounded snapshot-order label such as `gpu="0"`.
GPU names, processes, diagnostics, and error strings are not labels. CPU temperature and GPU series
are omitted when unavailable rather than reported as zero; a GPU that disappears from the latest
snapshot also disappears from exposition. `systempulse_up`, the latest successful sample timestamp,
sample age, and a sampling-error counter describe exporter health. After a sampling failure, the
last valid core sample remains available while `systempulse_up` is 0 and sample age keeps increasing.

SystemPulse's SQLite history and AlertEngine remain separate. The exporter neither reads nor writes
history, and it does not expose per-process or historical-alert metrics.

Minimal Prometheus scrape configuration:

```yaml
scrape_configs:
  - job_name: systempulse
    static_configs:
      - targets:
          - "127.0.0.1:9100"
```

## CPU Temperature Notes

Temperature sensor access is OS- and hardware-dependent. Linux commonly exposes CPU sensors through `psutil.sensors_temperatures()`. Windows and macOS may not expose a CPU temperature through `psutil`; in that case SystemPulse displays `Unavailable` and continues normally.

## CSV Logging

SystemPulse can record timestamp, CPU/RAM/disk usage, raw byte counts, CPU temperature when available, network totals and speeds, and NVIDIA GPU metrics when available.

Each row now comes from one authoritative sample. Network rates are derived from an earlier counter
reading with a monotonic clock, while the row timestamp is timezone-aware UTC.

The default output file is `system_log.csv`.

SQLite history is additional functionality and does not replace CSV. `systempulse snapshot` remains
display-only, while `systempulse live` writes each authoritative sample and its same-cycle alert
transitions in one SQLite transaction. Collector diagnostics remain runtime-only and are not stored.

History is local to the machine and contains normalized rows for snapshots, every GPU in each
snapshot, and alert transition events. Cleanup runs once when a history-enabled live session starts;
expired snapshots cascade to their GPU and alert-event rows. SystemPulse does not run `VACUUM` per
sample.

History summaries report the change between the first and last observed network counters in the
selected period. This is explicitly a counter change, not a guaranteed transfer total; it is shown as
unavailable when there are fewer than two samples or a counter reset is detected.

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
sample to CSV, `alerts.py` evaluates snapshots and owns process-local alert state, `monitor.py`
schedules the live terminal display and invokes the alert engine, `history.py` owns SQLite schema,
transactions, retention, and queries, `exporter.py` independently samples `MonitorService` into a
lock-protected latest-snapshot state and exposes it through a dedicated Prometheus registry, and
`cli.py` handles commands.

The live display is scheduled against monotonic target ticks. Its first sample is immediate; each
later sample starts at the configured tick. If collection runs past one or more ticks, those ticks are
skipped rather than replayed, and the next future tick remains anchored to the existing schedule.

Alert duration is measured with a monotonic clock. The timer starts when a metric first reaches any
alert threshold, continues if it escalates while pending, and is cancelled if the metric recovers or
becomes unavailable before opening. Open alerts escalate immediately at the critical threshold and
recover only below `threshold - hysteresis`. A missing active metric holds its last state and does not
produce a false resolution. Transition events are emitted only for open, escalation, de-escalation,
and resolution; cooldown delays reopening after a resolution. GPU rules are evaluated independently
using stable snapshot-order identities such as `gpu.0.usage` and `gpu.1.temperature`.

Alert state and recent events exist only for the lifetime of the live process and are bounded by
`alerts.history_limit`; active state is not persisted. Transition events are persisted when SQLite
history is enabled and can be read with `systempulse alerts --history`. `systempulse snapshot`
remains a stateless one-shot metric view and does not manufacture duration-based alert state or write
history. Plain `systempulse alerts` continues to show configured rules.

## What Changed in 1.1.0

- Added Windows system-drive detection instead of assuming the Unix `/` filesystem root
- Kept `/` as the correct root on macOS and Linux
- Made missing/unsupported temperature APIs explicitly safe across platforms
- Added cross-platform collector tests
- Expanded GitHub Actions to Windows, macOS, and Linux
- Updated package metadata and documentation to describe cross-platform support accurately

## License

This project is licensed under the MIT License.
