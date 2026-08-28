import importlib.metadata
import tomllib
from pathlib import Path

import systempulse


def test_runtime_version_matches_installed_distribution_metadata():
    assert systempulse.__version__ == "2.0.0"
    assert importlib.metadata.version("systempulse") == systempulse.__version__


def test_pyproject_uses_package_version_as_single_source():
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert "version" not in pyproject["project"]
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "systempulse.__version__"
    }
    assert pyproject["project"]["scripts"]["systempulse"] == "systempulse.cli:main"


def test_prometheus_client_is_an_optional_extra_not_a_base_dependency():
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert not any(
        dependency.startswith("prometheus-client")
        for dependency in pyproject["project"]["dependencies"]
    )
    assert pyproject["project"]["optional-dependencies"]["prometheus"] == [
        "prometheus-client>=0.24,<1"
    ]
