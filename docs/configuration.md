# Configuration

SystemPulse uses a typed, validated JSON configuration. Every section is optional: omitted values
fall back to built-in defaults. Unknown keys, invalid types, non-finite numbers, and invalid ranges
are rejected before monitoring starts.

## Discovery and precedence

Configuration is selected in this order, from highest to lowest priority:

1. `--config PATH` on the command line.
2. The `SYSTEMPULSE_CONFIG` environment variable.
3. A legacy `config.json` in the current working directory.
4. The platform user configuration file.
5. Built-in defaults when no file is found.

An explicitly selected file and a file selected through `SYSTEMPULSE_CONFIG` must exist. A missing
explicit or environment-selected file is an error; an absent legacy or user file falls back to the
built-in defaults.

Typical user configuration locations are:

| Platform | User configuration |
|---|---|
| Windows | `%APPDATA%\SystemPulse\config.json` |
| macOS | `~/Library/Application Support/SystemPulse/config.json` |
| Linux | `~/.config/SystemPulse/config.json` |

`platformdirs` selects the exact path for the current machine. Use this command instead of assuming
a location:

```bash
systempulse config path
```

Relative explicit paths are resolved from the current working directory. `~` is expanded.

## Configuration commands

```bash
systempulse config path
systempulse config show
systempulse show-config
systempulse config init
systempulse config init --force
systempulse config set cpu.warning 70
systempulse config set alerts.cpu.duration 30
systempulse --config custom.json config show
systempulse --config custom.json config set history.retention_days 14
```

- `config show` prints the fully merged and validated configuration. `show-config` is its legacy
  alias.
- `config init` writes all built-in defaults to the user configuration path. It refuses to replace
  an existing file unless `--force` is supplied.
- `config set` parses the supplied value as JSON when possible, applies one supported key, validates
  the complete result, and writes atomically. Plain strings do not require JSON quoting.
- Global `--config` must appear before `config` or any other subcommand.

## Sections and keys

### Presentation thresholds

The `thresholds` section controls Normal/Warning/Critical status colors in the terminal UI. Values
are percentages from 0 through 100, and each warning value must be lower than its critical value.

```text
cpu_warning, cpu_critical
memory_warning, memory_critical
disk_warning, disk_critical
temperature_warning, temperature_critical
gpu_warning, gpu_critical
```

These thresholds are separate from stateful alert rules. Changing a UI status threshold does not
silently change alert behavior.

### Monitor timing

| Key | Type | Default | Meaning |
|---|---:|---:|---|
| `monitor.refresh_interval` | number > 0 | `2.0` | Target live-dashboard interval in seconds. |
| `monitor.cpu_sample_interval` | number ≥ 0 | `0.2` | Blocking interval passed to `psutil.cpu_percent`. |

Live and exporter schedules use monotonic target ticks. The exporter has its own independently
configured interval under `prometheus`.

### Processes, temperature, and CSV

| Key | Type | Default | Meaning |
|---|---:|---|---|
| `processes.limit` | positive integer | `5` | Default number of processes displayed. |
| `processes.sample_interval` | number > 0 | `1.0` | Process CPU sampling delay in seconds. |
| `temperature.preferred_sensors` | string array | platform-neutral sensor names | Ordered sensor groups preferred for CPU temperature. |
| `logging.csv_path` | non-empty string | `system_log.csv` | CSV destination used by `systempulse save`. |

Relative CSV paths are interpreted from the process working directory. The `save --output PATH`
option overrides `logging.csv_path` for one invocation.

### Alerts

`alerts.enabled` enables or disables the complete stateful alert engine. `alerts.history_limit` is a
positive integer bounding recent in-memory events.

The available rules are:

```text
alerts.cpu
alerts.memory
alerts.disk
alerts.cpu_temperature
alerts.gpu_usage
alerts.gpu_temperature
```

Each rule accepts:

| Key | Type | Meaning |
|---|---:|---|
| `enabled` | Boolean | Enable this metric rule. |
| `warning` | percentage | Warning entry threshold. |
| `critical` | percentage | Critical entry threshold; must exceed warning. |
| `duration` | seconds ≥ 0 | Time continuously beyond a threshold before opening. |
| `cooldown` | seconds ≥ 0 | Delay before a resolved metric may open again. |
| `hysteresis` | percentage points ≥ 0 | Recovery margin; must be lower than warning. |

Temperature rule values are validated as percentages because all alert thresholds share the same
0–100 validation model; operationally, temperature values are compared in degrees Celsius. See
[alerts.md](alerts.md) for transition behavior.

### History

| Key | Type | Default | Meaning |
|---|---:|---|---|
| `history.enabled` | Boolean | `true` | Enable live snapshot and alert-event persistence. |
| `history.database` | non-empty path string | OS user data directory | SQLite database path. |
| `history.retention_days` | positive integer | `30` | Age cutoff applied when a history-enabled live session starts. |

A relative database path is resolved from the process working directory. The generated default uses
the platform-specific user data directory; see [history.md](history.md).

### Prometheus

| Key | Type | Default | Meaning |
|---|---:|---|---|
| `prometheus.host` | hostname or IP string | `127.0.0.1` | HTTP bind address, not a URL. |
| `prometheus.port` | integer 1–65535 | `9100` | HTTP listen port. |
| `prometheus.interval` | number > 0 | `5.0` | System sampling interval in seconds. |

`systempulse serve --host`, `--port`, and `--interval` override these three values for one exporter
invocation.

## Complete valid example

The following structure is generated from `AppConfig.to_dict()`. Only the database path was changed
to a portable relative example; the complete document is accepted by the real loader.

```json
{
  "thresholds": {
    "cpu_warning": 60.0,
    "cpu_critical": 80.0,
    "memory_warning": 75.0,
    "memory_critical": 90.0,
    "disk_warning": 80.0,
    "disk_critical": 90.0,
    "temperature_warning": 70.0,
    "temperature_critical": 85.0,
    "gpu_warning": 75.0,
    "gpu_critical": 90.0
  },
  "monitor": {
    "refresh_interval": 2.0,
    "cpu_sample_interval": 0.2
  },
  "logging": {
    "csv_path": "system_log.csv"
  },
  "processes": {
    "limit": 5,
    "sample_interval": 1.0
  },
  "temperature": {
    "preferred_sensors": [
      "k10temp",
      "coretemp",
      "zenpower",
      "cpu_thermal"
    ]
  },
  "alerts": {
    "enabled": true,
    "history_limit": 100,
    "cpu": {
      "enabled": true,
      "warning": 60.0,
      "critical": 80.0,
      "duration": 0.0,
      "cooldown": 60.0,
      "hysteresis": 5.0
    },
    "memory": {
      "enabled": true,
      "warning": 75.0,
      "critical": 90.0,
      "duration": 0.0,
      "cooldown": 60.0,
      "hysteresis": 5.0
    },
    "disk": {
      "enabled": true,
      "warning": 80.0,
      "critical": 90.0,
      "duration": 0.0,
      "cooldown": 60.0,
      "hysteresis": 5.0
    },
    "cpu_temperature": {
      "enabled": true,
      "warning": 70.0,
      "critical": 85.0,
      "duration": 0.0,
      "cooldown": 60.0,
      "hysteresis": 5.0
    },
    "gpu_usage": {
      "enabled": true,
      "warning": 75.0,
      "critical": 90.0,
      "duration": 0.0,
      "cooldown": 60.0,
      "hysteresis": 5.0
    },
    "gpu_temperature": {
      "enabled": true,
      "warning": 70.0,
      "critical": 85.0,
      "duration": 0.0,
      "cooldown": 60.0,
      "hysteresis": 5.0
    }
  },
  "history": {
    "enabled": true,
    "database": "history/systempulse.db",
    "retention_days": 30
  },
  "prometheus": {
    "host": "127.0.0.1",
    "port": 9100,
    "interval": 5.0
  }
}
```

## Supported `config set` names

The shorter status-threshold aliases are:

```text
cpu.warning, cpu.critical
ram.warning, ram.critical
memory.warning, memory.critical
disk.warning, disk.critical
temperature.warning, temperature.critical
gpu.warning, gpu.critical
```

Direct settings include:

```text
monitor.refresh_interval, monitor.cpu_sample_interval
logging.csv_path
processes.limit, processes.sample_interval
temperature.preferred_sensors
alerts.enabled, alerts.history_limit
history.enabled, history.database, history.retention_days
prometheus.host, prometheus.port, prometheus.interval
```

For every alert rule name—`cpu`, `memory`, `disk`, `cpu_temperature`, `gpu_usage`, and
`gpu_temperature`—the following suffixes are supported:

```text
enabled, warning, critical, duration, cooldown, hysteresis
```

For example: `alerts.gpu_temperature.hysteresis`.
