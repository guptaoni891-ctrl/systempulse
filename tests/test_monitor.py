from types import SimpleNamespace
from unittest.mock import Mock, call

import systempulse.monitor as monitor
from systempulse.models import NetworkSpeed


class FakeLive:
    def __init__(self, renderable, **kwargs):
        self.renderable = renderable
        self.kwargs = kwargs
        self.updates = []
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.exited = True

    def update(self, renderable):
        self.updates.append(renderable)


def _capture_live(monkeypatch):
    instances = []

    def factory(renderable, **kwargs):
        instance = FakeLive(renderable, **kwargs)
        instances.append(instance)
        return instance

    monkeypatch.setattr(monitor, "Live", factory)
    return instances


def test_live_monitor_collects_and_renders_repeated_snapshots(monkeypatch):
    config = {"monitor": {"refresh_interval": 1.5}}
    snapshots = [
        SimpleNamespace(network="network 1"),
        SimpleNamespace(network="network 2"),
        SimpleNamespace(network="network 3"),
    ]
    speeds = [NetworkSpeed(10.0, 20.0), NetworkSpeed(30.0, 40.0)]
    collect = Mock(side_effect=snapshots)
    sleep = Mock(side_effect=[None, None, KeyboardInterrupt])
    monotonic = Mock(side_effect=[10.0, 12.0, 15.0])
    calculate = Mock(side_effect=speeds)
    build = Mock(side_effect=["initial view", "second view", "third view"])
    instances = _capture_live(monkeypatch)
    monkeypatch.setattr(monitor, "collect_system_snapshot", collect)
    monkeypatch.setattr(monitor.time, "sleep", sleep)
    monkeypatch.setattr(monitor.time, "monotonic", monotonic)
    monkeypatch.setattr(monitor, "calculate_network_speed", calculate)
    monkeypatch.setattr(monitor, "build_snapshot_view", build)

    monitor.live_monitor(config)

    assert collect.mock_calls == [call(config, include_gpu=True)] * 3
    assert sleep.mock_calls == [call(1.5), call(1.5), call(1.5)]
    assert calculate.mock_calls == [
        call(snapshots[0].network, snapshots[1].network, 2.0),
        call(snapshots[1].network, snapshots[2].network, 3.0),
    ]
    assert build.mock_calls == [
        call(snapshots[0], config, NetworkSpeed(0.0, 0.0)),
        call(snapshots[1], config, speeds[0]),
        call(snapshots[2], config, speeds[1]),
    ]
    assert len(instances) == 1
    assert instances[0].renderable == "initial view"
    assert instances[0].kwargs == {"refresh_per_second": 4, "screen": True}
    assert instances[0].updates == ["second view", "third view"]
    assert instances[0].entered is True
    assert instances[0].exited is True


def test_live_monitor_clamps_refresh_and_handles_keyboard_interrupt(monkeypatch):
    config = {"monitor": {"refresh_interval": 0}}
    snapshot = object()
    collect = Mock(return_value=snapshot)
    sleep = Mock(side_effect=KeyboardInterrupt)
    instances = _capture_live(monkeypatch)
    monkeypatch.setattr(monitor, "collect_system_snapshot", collect)
    monkeypatch.setattr(monitor.time, "sleep", sleep)
    monkeypatch.setattr(monitor.time, "monotonic", Mock(return_value=10.0))
    monkeypatch.setattr(monitor, "build_snapshot_view", Mock(return_value="view"))

    result = monitor.live_monitor(config, include_gpu=False)

    assert result is None
    collect.assert_called_once_with(config, include_gpu=False)
    sleep.assert_called_once_with(0.2)
    assert instances[0].updates == []
    assert instances[0].exited is True
