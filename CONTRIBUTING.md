# Contributing to SystemPulse

Contributions are welcome when they keep SystemPulse focused as a lightweight cross-platform
terminal monitoring and observability tool.

## Workflow

1. Fork the repository and create a focused branch from the current default branch.
2. Set up a development environment using [docs/development.md](docs/development.md).
3. Make the smallest coherent change that solves the problem.
4. Add or update tests for behavior changes and bug fixes.
5. Run the local quality checks.
6. Open a pull request that explains the motivation, behavior, platform impact, and verification.

Useful branch names include `fix/gpu-timeout`, `docs/config-precedence`, or
`feat/<narrow-capability>`. A branch name is less important than keeping its scope clear.

## Required local checks

```bash
python -m pytest
python -m pytest --cov=systempulse --cov-report=term-missing
python -m ruff check .
python -m ruff format --check .
python -m mypy src/systempulse
pre-commit run --all-files
```

For packaging or dependency changes, also run:

```bash
python -m build
python -m twine check dist/*
```

CI repeats quality checks, tests the supported Python and operating-system matrix, and validates
clean base and Prometheus-extra installations.

## Tests

- Add a regression test before fixing a reproducible bug.
- Keep tests deterministic and independent of the developer machine.
- Use temporary paths for SQLite, configuration, and CSV data.
- Mock GPUs, sensors, subprocesses, clocks, and sleeps; the suite must not require privileged access
  or specialized hardware.
- Exercise observable behavior without asserting large blocks of terminal formatting.
- Preserve explicit tests for installations without `prometheus-client`.

The project enforces 90% branch coverage, but useful boundary and failure-path tests matter more than
executing lines without meaningful assertions.

## Code and architecture

- Preserve the authoritative `SystemSnapshot` boundary: collectors collect, `MonitorService`
  assembles, and sinks consume.
- Do not make Prometheus scrapes trigger hardware collection.
- Keep optional integrations optional and degrade gracefully when telemetry is unavailable.
- Use timezone-aware UTC timestamps for persisted or exchanged wall-clock time and monotonic clocks
  for elapsed intervals.
- Avoid unrelated refactors inside a feature or bug-fix pull request.
- Update documentation when a public command, configuration key, metric, or behavior changes.

See [docs/architecture.md](docs/architecture.md) before changing component responsibilities.

## Commit messages

The repository uses concise Conventional Commit-style subjects. Examples:

```text
fix(history): report unsupported schema versions clearly
test(alerts): cover cooldown boundary
docs: clarify source installation
```

Use a scope when it adds useful context; it is not required for repository-wide documentation or
maintenance work.

## Pull requests

A good pull request includes:

- The problem and why it matters.
- The chosen approach and important tradeoffs.
- User-visible or compatibility impact.
- Tests and commands run.
- Relevant platform notes for Windows, macOS, and Linux.
- Screenshots only when terminal presentation changes.

Keep generated build artifacts, local databases, CSV logs, virtual environments, and private config
files out of the pull request.
