# Changelog

All notable changes to SystemPulse are documented here. The format is inspired by
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses semantic versioning
for release planning.

## [Unreleased]

## [2.1.0] - 2026-09-15

### Added

- CPU package power where supported, aggregate NVIDIA GPU power, combined measured CPU + GPU
  power, and explicitly estimated system and wall power.
- Live Power Session and SQLite Power History statistics with time-weighted averages, peaks,
  telemetry-aware observed durations, and trapezoidal Wh/kWh energy integration.
- SQLite schema v2 persistence, CSV V2 fields, and instantaneous Prometheus gauges for power
  telemetry.
- `systempulse speedtest`, an on-demand global internet benchmark using Cloudflare edge
  infrastructure for download and upload Mbps, median unloaded HTTP latency, jitter, and optional
  edge colo metadata.

### Changed

- Advanced SQLite history to schema version 2 with an automatic in-place migration that preserves
  existing schema-v1 snapshots, GPUs, and alert events.
- Preserved exact legacy V1 CSV append compatibility while rejecting unknown headers.
- Kept `systempulse network --speed` as local current-interface throughput, distinct from the
  active internet benchmark.
- Replaced the geolocation-dependent `speedtest-cli` backend with a persistent HTTP/2-capable HTTPX
  client routed by Cloudflare's global anycast edge.

### Fixed

- Removed geographic server selection that could benchmark against a distant country when a
  third-party client-geolocation result was incorrect.
- Corrected Cloudflare unloaded latency to measure response-header arrival, drain responses for
  connection reuse, exclude the warm-up, and subtract valid edge processing time.
- Aligned Cloudflare bandwidth measurement with repeated, adaptively stopped size sets and P90
  reduction over only the final stable set, avoiding distortion from tiny ramp-up transfers.
- Kept unavailable optional power telemetry, Cloudflare edge metadata, and unsupported sensors
  non-fatal, without inventing zero values or inferred locations.

## [2.0.0] - 2026-08-28

### Added

- Stateful `AlertEngine` rules for CPU, memory, disk, optional CPU temperature, GPU usage, and GPU
  temperature, with duration, hysteresis, cooldown, and explicit transition events.
- Transactional SQLite history for authoritative snapshots, normalized multi-GPU rows, and durable
  alert transitions.
- Schema version validation, UTC history queries, configurable retention, and history/alert-history
  CLI views.
- Optional Prometheus exporter with a dedicated registry, exporter health metrics, bounded GPU
  labels, and scrape-decoupled latest-snapshot state.
- Typed, validated configuration for alerts, history, and Prometheus plus `config show`, `path`,
  `init`, and validated `set` commands.
- OS-specific user configuration and data paths through `platformdirs`, while preserving legacy
  local `config.json` discovery.
- Structured optional-collector diagnostics for unavailable sensors and NVIDIA command failures.
- Branch coverage enforcement, mypy, Ruff formatting, pre-commit, package smoke tests, and a focused
  cross-platform CI matrix.

### Changed

- Centralized collection in `MonitorService`, producing one immutable authoritative
  `SystemSnapshot` per sampling cycle.
- Made the Rich UI, alert engine, CSV logger, SQLite store, and Prometheus state consumers of
  snapshots instead of independent collectors.
- Standardized persisted and model timestamps as timezone-aware UTC.
- Anchored live and exporter scheduling, alert timing, network-rate intervals, and sample age to
  monotonic clocks.
- Improved packaging with explicit Python support metadata, optional Prometheus dependencies, wheel
  and sdist validation, and clean-install verification.
- Expanded GPU handling so every GPU can be represented independently in alerts, SQLite, and
  Prometheus while retaining the established first-GPU CSV shape.

### Fixed

- Made CSV save use one coherent snapshot whose network rate is derived from a prior counter
  observation rather than combining independently timed readings.
- Handled platforms where the `psutil` temperature API is absent, unsupported, empty, or malformed
  without breaking core monitoring.
- Converted corrupt SQLite timestamps, incomplete schemas, future schema versions, missing insert
  identifiers, and operational database failures into controlled history errors.
- Prevented negative instantaneous network rates and misleading negative historical transfer values
  when operating-system counters reset.
- Preserved live monitoring when history initialization or persistence fails by disabling the sink
  and surfacing a compact warning.
