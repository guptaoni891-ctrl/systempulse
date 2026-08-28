# Prometheus exporter

SystemPulse can expose the latest in-memory system sample in Prometheus text format. The exporter is
an optional installation mode so normal terminal and history use does not require
`prometheus-client`.

## Installation and startup

For the current source checkout:

```bash
python -m pip install -e ".[prometheus]"
systempulse serve
```

After SystemPulse is published to PyPI, the equivalent installation will be:

```bash
pip install "systempulse[prometheus]"
systempulse serve
```

The default endpoint is:

```text
http://127.0.0.1:9100/metrics
```

Override exporter settings for one invocation:

```bash
systempulse serve --host 127.0.0.1 --port 9200 --interval 2
```

The equivalent persistent settings are `prometheus.host`, `prometheus.port`, and
`prometheus.interval` in configuration.

## Binding and security

The default `127.0.0.1` bind is reachable only from the local host. SystemPulse's exporter uses
plain HTTP and provides no authentication, authorization, or TLS. Binding to `0.0.0.0` or another
non-loopback address exposes host metrics on every reachable interface covered by that bind.

Use firewalling, a trusted network, or an authenticated reverse proxy when remote access is
required. See [../SECURITY.md](../SECURITY.md) for the concise security policy.

## Sampling is independent of scraping

`prometheus.interval` controls how often the exporter sampling thread calls `MonitorService`.
Prometheus's scrape interval controls only how often Prometheus reads the HTTP endpoint. The two
intervals are intentionally independent.

A scrape reads a lock-protected latest-state object. It does **not** call `MonitorService`, `psutil`,
temperature sensors, or `nvidia-smi`. Slow or frequent scrapes therefore do not increase hardware
polling frequency.

If a sampling attempt fails, `systempulse_up` becomes 0 and the error counter increases. The last
successful snapshot remains available, and its age continues increasing until a later sample
succeeds.

## Exported metrics

| Metric | Type | Unit | Description |
|---|---|---|---|
| `systempulse_up` | Gauge | boolean | `1` when the latest sampling attempt succeeded, otherwise `0`. |
| `systempulse_sampling_errors_total` | Counter | attempts | Failed sampling attempts since exporter startup. |
| `systempulse_last_sample_timestamp_seconds` | Gauge | Unix seconds | Wall-clock timestamp of the latest successful sample. |
| `systempulse_sample_age_seconds` | Gauge | seconds | Monotonic age of the latest successful sample. |
| `systempulse_cpu_usage_ratio` | Gauge | ratio | CPU usage from 0 to 1. |
| `systempulse_memory_usage_ratio` | Gauge | ratio | Memory usage from 0 to 1. |
| `systempulse_memory_used_bytes` | Gauge | bytes | Current used memory. |
| `systempulse_memory_total_bytes` | Gauge | bytes | Total memory. |
| `systempulse_disk_usage_ratio` | Gauge | ratio | System-disk usage from 0 to 1. |
| `systempulse_disk_used_bytes` | Gauge | bytes | Current used system-disk space. |
| `systempulse_disk_total_bytes` | Gauge | bytes | Total system-disk space. |
| `systempulse_cpu_temperature_celsius` | Gauge | °C | CPU temperature when available. |
| `systempulse_network_bytes_sent_total` | Counter | bytes | OS cumulative sent counter since its last reset. |
| `systempulse_network_bytes_received_total` | Counter | bytes | OS cumulative received counter since its last reset. |
| `systempulse_network_upload_bytes_per_second` | Gauge | bytes/second | Calculated upload rate. |
| `systempulse_network_download_bytes_per_second` | Gauge | bytes/second | Calculated download rate. |
| `systempulse_gpu_usage_ratio` | Gauge | ratio | GPU usage from 0 to 1, labeled by `gpu`. |
| `systempulse_gpu_temperature_celsius` | Gauge | °C | GPU temperature, labeled by `gpu`. |
| `systempulse_gpu_memory_used_bytes` | Gauge | bytes | Used GPU memory, labeled by `gpu`. |
| `systempulse_gpu_memory_total_bytes` | Gauge | bytes | Total GPU memory, labeled by `gpu`. |
| `systempulse_gpu_power_watts` | Gauge | watts | GPU power when reported, labeled by `gpu`. |

Usage values are converted from internal percentages to ratios at the exporter boundary. Optional
CPU temperature is omitted when unavailable. All GPU series are omitted when no GPU is available,
and GPU power is omitted for devices that do not report it.

The only GPU label is a bounded zero-based snapshot index such as `gpu="0"`. GPU names, process
names, diagnostics, paths, and error messages are not exported as labels.

SystemPulse intentionally exports no per-process metrics. SQLite history and durable alert events
are separate and are neither read nor written by the exporter.

## Prometheus scrape configuration

```yaml
scrape_configs:
  - job_name: systempulse
    static_configs:
      - targets:
          - "127.0.0.1:9100"
```

Choose a Prometheus `scrape_interval` independently from the SystemPulse sampling interval. No
Grafana or Alertmanager configuration is included in the current project scope.
