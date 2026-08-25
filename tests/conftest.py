from __future__ import annotations

import pytest

from systempulse.paths import CONFIG_ENV_VAR


@pytest.fixture(autouse=True)
def isolate_systempulse_environment(monkeypatch, tmp_path):
    """Prevent tests from discovering developer config or data locations."""
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
