from types import SimpleNamespace
from unittest.mock import Mock

import systempulse.paths as paths


def test_platform_directories_are_exposed_without_creating_them(monkeypatch, tmp_path):
    directories = SimpleNamespace(
        user_config_dir=str(tmp_path / "config"),
        user_data_dir=str(tmp_path / "data"),
        user_state_dir=str(tmp_path / "state"),
    )
    monkeypatch.setattr(paths, "_platform_dirs", lambda: directories)

    assert paths.user_config_dir() == tmp_path / "config"
    assert paths.user_config_path() == tmp_path / "config" / "config.json"
    assert paths.user_data_dir() == tmp_path / "data"
    assert paths.user_state_dir() == tmp_path / "state"
    assert not (tmp_path / "config").exists()


def test_default_history_database_uses_platform_data_directory(monkeypatch, tmp_path):
    data = tmp_path / "data"
    monkeypatch.setattr(paths, "user_data_dir", lambda: data)

    assert paths.default_history_database() == data / "systempulse.db"


def test_platformdirs_receives_application_identity(monkeypatch):
    mock = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(paths, "PlatformDirs", mock)

    paths._platform_dirs()

    mock.assert_called_once_with(appname="SystemPulse", appauthor=False, roaming=True)


def test_explicit_config_path_has_highest_precedence(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit.json"
    explicit.write_text("{}", encoding="utf-8")
    environment = tmp_path / "environment.json"
    environment.write_text("{}", encoding="utf-8")
    legacy = tmp_path / "config.json"
    legacy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths, "user_config_path", lambda: tmp_path / "user.json")

    result = paths.resolve_config_path(
        explicit,
        environ={paths.CONFIG_ENV_VAR: str(environment)},
        cwd=tmp_path,
    )

    assert result.path == explicit.resolve()
    assert result.source == "explicit"
    assert result.exists is True


def test_environment_path_is_selected_even_when_missing(monkeypatch, tmp_path):
    environment = tmp_path / "missing.json"
    legacy = tmp_path / "config.json"
    legacy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths, "user_config_path", lambda: tmp_path / "user.json")

    result = paths.resolve_config_path(
        environ={paths.CONFIG_ENV_VAR: str(environment)},
        cwd=tmp_path,
    )

    assert result.path == environment.resolve()
    assert result.source == "environment"
    assert result.exists is False


def test_legacy_path_precedes_user_config(monkeypatch, tmp_path):
    legacy = tmp_path / "config.json"
    legacy.write_text("{}", encoding="utf-8")
    user = tmp_path / "user" / "config.json"
    user.parent.mkdir()
    user.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths, "user_config_path", lambda: user)

    result = paths.resolve_config_path(environ={}, cwd=tmp_path)

    assert result.path == legacy.resolve()
    assert result.source == "legacy"


def test_user_path_is_selected_when_no_legacy_file(monkeypatch, tmp_path):
    user = tmp_path / "user" / "config.json"
    user.parent.mkdir()
    user.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths, "user_config_path", lambda: user)

    result = paths.resolve_config_path(environ={}, cwd=tmp_path)

    assert result.path == user.resolve()
    assert result.source == "user"
    assert result.exists is True


def test_missing_files_return_default_user_target(monkeypatch, tmp_path):
    user = tmp_path / "user" / "config.json"
    monkeypatch.setattr(paths, "user_config_path", lambda: user)

    result = paths.resolve_config_path(environ={}, cwd=tmp_path)

    assert result.path == user.resolve()
    assert result.source == "defaults"
    assert result.exists is False


def test_relative_explicit_path_is_resolved_against_supplied_working_directory(tmp_path):
    result = paths.resolve_config_path("settings.json", environ={}, cwd=tmp_path)

    assert result.path == (tmp_path / "settings.json").resolve()
    assert result.source == "explicit"
