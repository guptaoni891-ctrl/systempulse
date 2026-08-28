# Development

SystemPulse supports Python 3.11, 3.12, and 3.13. Use an isolated virtual environment and install
the `dev` extra from a source checkout.

## Environment setup

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Linux and macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The development extra includes tests, coverage, Ruff, mypy, type stubs, pre-commit, packaging tools,
and `prometheus-client` for exporter tests. Runtime dependencies remain limited to `platformdirs`,
`psutil`, and Rich; Prometheus support is still optional for users.

## Local checks

Run the normal test suite:

```bash
python -m pytest
```

Measure branch coverage against the real package and show missing lines:

```bash
python -m pytest --cov=systempulse --cov-report=term-missing
```

Coverage is configured in `pyproject.toml`, includes branch measurement, and enforces a 90% total
floor. XML output for CI is available with `--cov-report=xml`.

Run lint, format verification, and static typing:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src/systempulse
```

Apply Ruff's formatter when needed:

```bash
python -m ruff format .
```

Install and run the fast commit hooks:

```bash
pre-commit install
pre-commit run --all-files
```

The hooks check trailing whitespace, final newlines, YAML, TOML, Ruff lint/fixes, and Ruff formatting.
They intentionally do not run the full cross-platform test suite.

## Package validation

Build both distribution formats and validate their metadata:

```bash
python -m build
python -m twine check dist/*
```

Before a release, install the wheel into a fresh environment rather than importing from the source
tree. Verify both modes:

1. Base wheel: no `prometheus-client`, with `systempulse --help`, `--version`, and `snapshot` working.
2. Prometheus wheel extra: exporter import and `systempulse serve --help` working.

The project version comes from `systempulse.__version__`; do not change it incidentally in feature or
documentation work.

## CI pipeline

The GitHub Actions workflow has three jobs:

### Quality

Runs on Ubuntu with Python 3.13 and performs:

- Ruff lint.
- Ruff format verification.
- mypy over `src/systempulse`.
- pytest with branch coverage and XML output.

### Tests

Runs pytest with warnings treated as errors on this efficient matrix:

| Operating system | Python versions |
|---|---|
| Ubuntu | 3.11, 3.12, 3.13 |
| Windows | 3.13 |
| macOS | 3.13 |

This tests every declared Python minor on Linux and representative current-Python behavior on all
three supported operating systems.

### Package

Builds the sdist and wheel, runs Twine metadata validation, installs the wheel into clean temporary
environments, verifies that the base install excludes Prometheus, and separately verifies the
`prometheus` extra.

The workflow uses read-only repository permissions, maintained action major versions, setup-python's
pip cache, job timeouts, and concurrency cancellation.

## Test design expectations

- Use `tmp_path` for databases, configuration, CSV, and other filesystem state.
- Do not read a developer's `SYSTEMPULSE_CONFIG` or local `config.json` unless that behavior is the
  subject of the test.
- Mock hardware, clocks, subprocesses, and sleep calls; tests must not require a GPU, temperature
  sensor, network access, administrator privileges, or real delays.
- Add regression coverage before fixing a behavior bug.
- Prefer public outcomes and stable boundaries over brittle assertions against large Rich renderings
  or private implementation sequences.
- Keep optional dependency tests explicit: most exporter tests install the dev dependency, while
  dedicated tests cover the missing-dependency path.
