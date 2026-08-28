# Alerts

SystemPulse evaluates configurable threshold rules while `systempulse live` is running. The
`AlertEngine` consumes completed `SystemSnapshot` objects; it does not collect metrics itself.

## Severity states

| State | Meaning |
|---|---|
| `NORMAL` | The metric has no open alert. It may still be waiting through a configured duration. |
| `WARNING` | The metric has opened at or above its warning threshold. |
| `CRITICAL` | The metric has opened or escalated at or above its critical threshold. |

CPU usage, memory usage, disk usage, optional CPU temperature, GPU usage, and GPU temperature have
independent rules. Rules can be disabled individually or disabled together with `alerts.enabled`.

## Transition events

The engine emits events only when state changes:

| Transition | Meaning |
|---|---|
| `OPENED` | A normal metric completed its duration and entered Warning or Critical. |
| `ESCALATED` | An open Warning metric reached Critical. |
| `DEESCALATED` | An open Critical metric recovered into Warning. |
| `RESOLVED` | An open metric recovered to Normal. |

Repeated samples in the same state do not emit duplicate events.

Example with warning `70`, critical `90`, and hysteresis `5`:

```text
72  -> OPENED as WARNING after duration
93  -> ESCALATED to CRITICAL
84  -> DEESCALATED to WARNING (below 90 - 5)
64  -> RESOLVED (below 70 - 5)
```

Threshold equality opens or escalates. Recovery requires crossing below the hysteresis-adjusted
boundary, which prevents noisy values near a threshold from repeatedly opening and resolving an
alert.

## Duration, hysteresis, and cooldown

### Duration

`duration` is the number of continuous monotonic seconds a normal metric must remain at or above an
alert threshold before it opens. The timer starts on the first qualifying observation. If the value
escalates from the warning range into the critical range while pending, the same timer continues. A
recovery or missing metric before opening cancels the pending timer.

The default duration is `0`, so alerts open on the first qualifying sample.

### Hysteresis

`hysteresis` is subtracted from an open state's threshold during recovery:

- Warning resolves below `warning - hysteresis`.
- Critical remains Critical at or above `critical - hysteresis`.
- Critical de-escalates to Warning below that boundary while still at or above
  `warning - hysteresis`.
- Critical resolves when it also falls below `warning - hysteresis`.

### Cooldown

After resolution, `cooldown` prevents that metric identity from reopening until the configured
monotonic interval expires. Cooldown does not hide an already open alert.

## Missing metrics

Optional CPU temperature and GPU observations may disappear because a sensor is unavailable,
`nvidia-smi` fails, or a GPU is no longer present.

- A missing metric that has not opened cancels its pending duration.
- A missing active metric holds its last active state; absence does not create a false resolution.
- A later observation resumes evaluation from that held state.

This behavior favors explicit recovery evidence over assuming that missing telemetry means healthy.

## Multiple GPUs

Each GPU is evaluated independently using its zero-based snapshot position:

```text
gpu.0.usage
gpu.0.temperature
gpu.1.usage
gpu.1.temperature
```

Human-readable event labels include the GPU name, while the metric identity remains bounded by
snapshot order. Reordering devices between snapshots may therefore change which physical device an
index represents.

## Active state versus durable history

Active alert state belongs to the running `AlertEngine`:

- It is displayed by `systempulse live`.
- It is not restored after the process restarts.
- Recent in-memory events are bounded by `alerts.history_limit`.
- `systempulse snapshot` does not create duration-based alert state.

Transition events are separate durable records when SQLite history is enabled. The live monitor
writes each snapshot and its same-cycle transitions in one database transaction. Inspect them with:

```bash
systempulse alerts --history
systempulse alerts --history --limit 50
```

Plain `systempulse alerts` prints configured rules and explains the process-local state limitation;
it does not reconstruct active state from SQLite.

If history is disabled, live alerts still work but transition events are not persisted. See
[history.md](history.md) and [configuration.md](configuration.md) for storage and rule settings.
