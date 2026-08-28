# Changelog

All notable changes to SystemPulse are documented here. The format is inspired by
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses semantic versioning
for release planning.

## [Unreleased]

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
