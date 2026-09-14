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
- Snapshot-level CPU package, aggregate GPU, combined CPU + GPU, estimated system, estimated wall,
  actual wall, and CPU power-source fields.
- Alert transition events produced from that same snapshot.

The snapshot, all GPU rows, and all same-cycle alert events are committed in one transaction. This
keeps events associated with the sample that caused them.

`systempulse live` writes history. One-shot `snapshot`, CSV `save`, and Prometheus `serve` do not
write to SQLite. The interactive menu writes only when its live-dashboard option is running.

## Schema versioning

The current database schema version is 2. SystemPulse records the version through SQLite's schema
version mechanism, creates and migrates schemas transactionally, validates required tables and
columns, and rejects databases created by a newer unsupported schema instead of guessing how to
read them.

An existing schema-v1 database is migrated automatically in place. Existing snapshot, GPU, and
alert data is preserved; the seven new snapshot power columns are added and are `NULL` (displayed
as unavailable) for old rows. The database is not rebuilt. Schema versions newer than 2 continue
to be rejected rather than opened with assumptions about their layout.

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
  information, a Power History panel, and recent samples including their power fields.
- `alerts --history` reads durable transition events; it does not restore active in-memory alerts.

## Power history and energy

Power History reports time-weighted averages and peaks for measured and derived power fields,
estimated- and actual-wall energy, and separate observed durations. The averages and energy are
calculated only from the timestamped values persisted in SQLite; current configuration is not used
to recompute old estimates.

For each pair of consecutive valid readings, SystemPulse applies trapezoidal integration:

```text
energy_Wh += ((P1 + P2) / 2) * elapsed_seconds / 3600
```

One Wh is one watt sustained for one hour, and 1000 Wh is 1 kWh. The time-weighted average is the
integrated energy divided by observed time. A lone reading can establish a peak, but it has no
interval and therefore contributes no energy or average.

Unavailable, negative, or non-finite readings break the series. If 100 W is recorded at 00:00,
power is unavailable at 00:30, and 100 W returns at 01:00, SystemPulse integrates no energy across
that gap. **Observed Duration** counts only intervals bounded by consecutive valid readings and can
therefore be shorter than the selected period.

`--hours` and `--days` filtering is conservative. Samples before the UTC cutoff are excluded
entirely, so a sample before the cutoff is never joined to one after it to create an interval that
crosses into the selected period. Estimated-wall and actual-wall series are integrated
independently.

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
