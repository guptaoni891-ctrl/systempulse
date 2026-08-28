# SQLite history

SystemPulse can persist live samples and alert transitions in a local SQLite database. History is
enabled by default and is designed as local observability storage, not as a remote time-series
database.

## Location

The default file is `systempulse.db` in the platform-specific SystemPulse user data directory:

| Platform | Typical default database |
|---|---|
| Windows | `%APPDATA%\SystemPulse\systempulse.db` |
| macOS | `~/Library/Application Support/SystemPulse/systempulse.db` |
| Linux | `~/.local/share/SystemPulse/systempulse.db` |

`platformdirs` determines the exact path. Display the effective value with:

```bash
systempulse config show
```

Override it with configuration:

```bash
systempulse config set history.database ./history/systempulse.db
```

Relative paths are resolved from the process working directory. Parent directories are created when
needed.

## What is persisted

A history-enabled live session stores:

- The authoritative UTC timestamp and core CPU, memory, disk, temperature, and network fields.
- The sample's calculated upload and download rates.
- One normalized child row for every GPU in the snapshot, including optional power.
- Alert transition events produced from that same snapshot.

The snapshot, all GPU rows, and all same-cycle alert events are committed in one transaction. This
keeps events associated with the sample that caused them.

`systempulse live` writes history. One-shot `snapshot`, CSV `save`, and Prometheus `serve` do not
write to SQLite. The interactive menu writes only when its live-dashboard option is running.

## Schema versioning

The current database schema version is 1. SystemPulse records the version through SQLite's schema
version mechanism, creates the initial schema transactionally, validates required tables and
columns, and rejects databases created by a newer unsupported schema instead of guessing how to
read them.

The schema separates snapshots, GPU samples, and alert events. This supports multiple GPUs without
duplicating snapshot-level metrics. Internal SQL and table layouts are implementation details and
may evolve through explicit future migrations.

## Retention

`history.retention_days` defaults to 30 and must be a positive integer. Cleanup runs once when a
history-enabled live or menu session prepares its history store. Snapshots older than the UTC cutoff
are deleted; associated GPU and alert-event rows are removed through the database relationships.

SystemPulse does not run `VACUUM` for every sample. Retention limits logical history but does not
promise that the SQLite file immediately shrinks on disk.

Disable persistence without disabling monitoring or in-memory alerts:

```bash
systempulse config set history.enabled false
```

If history initialization or a live write fails, the live dashboard continues and shows a compact
history warning for that session. Direct history commands report the storage error and return a
non-zero exit status.

## Querying history

```bash
systempulse history
systempulse history --limit 20
systempulse history --hours 24 --limit 20
systempulse history --days 7
systempulse alerts --history --limit 50
```

- `--hours` and `--days` filter from the current UTC time and cannot be combined.
- `--limit` controls the number of recent rows displayed, not the summary aggregation.
- `history` shows aggregate CPU, memory, disk, temperature, network-change, GPU, and alert-event
  information plus recent samples.
- `alerts --history` reads durable transition events; it does not restore active in-memory alerts.

## Network counter-change semantics

The operating system exposes cumulative network byte counters. For a selected history period,
SystemPulse reports the difference between the first and last observed sent counters and between the
first and last observed received counters.

These values are **observed counter changes**, not an exact integral of network traffic:

- Traffic before the first stored sample or after the last sample is not included.
- Gaps between samples can reduce interpretability.
- Fewer than two samples produces an unavailable result.
- A counter reset, represented by the last value being lower than the first, also produces an
  unavailable result rather than a negative transfer total.

Per-sample upload and download rates are stored separately and are derived from monotonic elapsed
time between observations.
