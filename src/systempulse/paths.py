from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "SystemPulse"
CONFIG_FILENAME = "config.json"
CONFIG_ENV_VAR = "SYSTEMPULSE_CONFIG"


@dataclass(frozen=True, slots=True)
class ConfigPath:
    path: Path
    source: str
    exists: bool


def _platform_dirs() -> PlatformDirs:
    return PlatformDirs(appname=APP_NAME, appauthor=False, roaming=True)


def user_config_dir() -> Path:
    return Path(_platform_dirs().user_config_dir)


def user_config_path() -> Path:
    return user_config_dir() / CONFIG_FILENAME


def user_data_dir() -> Path:
    return Path(_platform_dirs().user_data_dir)


def user_state_dir() -> Path:
    return Path(_platform_dirs().user_state_dir)


def _absolute_path(path: str | Path, cwd: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve(strict=False)


def resolve_config_path(
    explicit: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> ConfigPath:
    environment = os.environ if environ is None else environ
    working_directory = Path.cwd() if cwd is None else Path(cwd)

    if explicit is not None:
        path = _absolute_path(explicit, working_directory)
        return ConfigPath(path=path, source="explicit", exists=path.is_file())

    environment_path = environment.get(CONFIG_ENV_VAR)
    if environment_path:
        path = _absolute_path(environment_path, working_directory)
        return ConfigPath(path=path, source="environment", exists=path.is_file())

    legacy_path = (working_directory / CONFIG_FILENAME).resolve(strict=False)
    if legacy_path.is_file():
        return ConfigPath(path=legacy_path, source="legacy", exists=True)

    path = user_config_path().resolve(strict=False)
    if path.is_file():
        return ConfigPath(path=path, source="user", exists=True)

    return ConfigPath(path=path, source="defaults", exists=False)
