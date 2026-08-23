from unittest.mock import Mock

import psutil
import pytest

import systempulse.processes as processes


class FakeProcess:
    def __init__(self, pid, name, cpu_values, memory_percent=1.0):
        self.pid = pid
        self.info = {"pid": pid, "name": name}
        self._cpu_values = iter(cpu_values)
        self._memory_percent = memory_percent

    def cpu_percent(self, interval=None):
        value = next(self._cpu_values)
        if isinstance(value, BaseException):
            raise value
        return value

    def memory_percent(self):
        if isinstance(self._memory_percent, BaseException):
            raise self._memory_percent
        return self._memory_percent


def _no_sleeps(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(processes.time, "sleep", sleep)
    return sleep


def test_collects_sorts_and_limits_processes(monkeypatch):
    candidates = [
        FakeProcess(1, "low", [0.0, 5.0], 2.0),
        FakeProcess(2, "highest", [0.0, 40.0], 1.0),
        FakeProcess(3, "middle", [0.0, 15.0], 3.0),
    ]
    monkeypatch.setattr(processes.psutil, "process_iter", lambda attrs: iter(candidates))
    sleep = _no_sleeps(monkeypatch)

    result = processes.get_top_processes(limit=2, sample_interval=0.5)

    assert [item.pid for item in result] == [2, 3]
    assert result[0].name == "highest"
    assert result[0].cpu_percent == 40.0
    assert result[0].memory_percent == 1.0
    sleep.assert_called_once_with(0.5)


@pytest.mark.parametrize("limit", [0, -5])
def test_non_positive_limit_currently_returns_one_process(monkeypatch, limit):
    candidates = [
        FakeProcess(1, "first", [0.0, 10.0]),
        FakeProcess(2, "second", [0.0, 20.0]),
    ]
    monkeypatch.setattr(processes.psutil, "process_iter", lambda attrs: iter(candidates))
    _no_sleeps(monkeypatch)

    result = processes.get_top_processes(limit=limit, sample_interval=1.0)

    assert [item.pid for item in result] == [2]


def test_short_sample_interval_is_clamped(monkeypatch):
    monkeypatch.setattr(processes.psutil, "process_iter", lambda attrs: iter(()))
    sleep = _no_sleeps(monkeypatch)

    assert processes.get_top_processes(sample_interval=0) == []

    sleep.assert_called_once_with(0.1)


@pytest.mark.parametrize(
    "error",
    [
        psutil.NoSuchProcess(10),
        psutil.AccessDenied(10),
        psutil.ZombieProcess(10),
    ],
)
def test_expected_psutil_errors_during_initial_collection_are_skipped(monkeypatch, error):
    inaccessible = FakeProcess(10, "blocked", [error])
    healthy = FakeProcess(20, "healthy", [0.0, 5.0])
    monkeypatch.setattr(
        processes.psutil,
        "process_iter",
        lambda attrs: iter((inaccessible, healthy)),
    )
    _no_sleeps(monkeypatch)

    result = processes.get_top_processes()

    assert [item.pid for item in result] == [20]


@pytest.mark.parametrize(
    "error",
    [
        psutil.NoSuchProcess(10),
        psutil.AccessDenied(10),
        psutil.ZombieProcess(10),
    ],
)
def test_processes_disappearing_during_final_collection_are_skipped(monkeypatch, error):
    disappearing = FakeProcess(10, "gone", [0.0, error])
    healthy = FakeProcess(20, "healthy", [0.0, 5.0])
    monkeypatch.setattr(
        processes.psutil,
        "process_iter",
        lambda attrs: iter((disappearing, healthy)),
    )
    _no_sleeps(monkeypatch)

    result = processes.get_top_processes()

    assert [item.pid for item in result] == [20]


def test_missing_process_name_uses_unknown(monkeypatch):
    unnamed = FakeProcess(10, None, [0.0, 5.0])
    monkeypatch.setattr(processes.psutil, "process_iter", lambda attrs: iter((unnamed,)))
    _no_sleeps(monkeypatch)

    result = processes.get_top_processes()

    assert result[0].name == "Unknown"
