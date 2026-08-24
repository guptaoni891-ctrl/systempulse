from unittest.mock import Mock, call

import pytest

import systempulse.monitor as monitor
from systempulse.config import AppConfig, MonitorConfig


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


def _service(interval, snapshots):
    service = Mock()
    service.config = AppConfig(monitor=MonitorConfig(refresh_interval=interval))
    service.sample = Mock(side_effect=snapshots)
    return service


def test_live_monitor_renders_authoritative_service_samples(monkeypatch):
    snapshots = [object(), object(), object()]
    service = _service(1.5, snapshots)
    sleep = Mock(side_effect=[None, None, KeyboardInterrupt])
    monotonic = Mock(side_effect=[10.0, 10.0, 11.5, 11.5, 13.0, 13.0])
    build = Mock(side_effect=["initial view", "second view", "third view"])
    alert_engine = Mock()
    alert_engine.active_alerts = ()
    instances = _capture_live(monkeypatch)
    monkeypatch.setattr(monitor, "build_snapshot_view", build)

    monitor.live_monitor(
        service,
        monotonic=monotonic,
        sleep=sleep,
        alert_engine=alert_engine,
    )

    assert service.sample.mock_calls == [call(), call(), call()]
    assert sleep.mock_calls == [call(1.5), call(1.5), call(1.5)]
    assert build.mock_calls == [
        call(
            snapshots[0],
            service.config,
            show_network_speed=True,
            active_alerts=(),
        ),
        call(
            snapshots[1],
            service.config,
            show_network_speed=True,
            active_alerts=(),
        ),
        call(
            snapshots[2],
            service.config,
            show_network_speed=True,
            active_alerts=(),
        ),
    ]
    assert alert_engine.evaluate.mock_calls == [
        call(snapshots[0]),
        call(snapshots[1]),
        call(snapshots[2]),
    ]
    assert len(instances) == 1
    assert instances[0].renderable == "initial view"
    assert instances[0].kwargs == {"refresh_per_second": 4, "screen": True}
    assert instances[0].updates == ["second view", "third view"]
    assert instances[0].entered is True
    assert instances[0].exited is True


def test_slow_collection_skips_missed_ticks_without_schedule_drift(monkeypatch):
    service = _service(2.0, [object(), object()])
    sleep = Mock(side_effect=[None, KeyboardInterrupt])
    monotonic = Mock(side_effect=[0.0, 0.0, 5.0, 5.0])
    _capture_live(monkeypatch)
    monkeypatch.setattr(monitor, "build_snapshot_view", Mock(return_value="view"))

    alert_engine = Mock(active_alerts=())

    monitor.live_monitor(
        service,
        monotonic=monotonic,
        sleep=sleep,
        alert_engine=alert_engine,
    )

    assert service.sample.call_count == 2
    assert sleep.mock_calls == [call(2.0), call(1.0)]


def test_refresh_interval_is_clamped_and_keyboard_interrupt_is_graceful(monkeypatch):
    service = _service(0.1, [object()])
    sleep = Mock(side_effect=KeyboardInterrupt)
    monotonic = Mock(side_effect=[10.0, 10.0])
    instances = _capture_live(monkeypatch)
    monkeypatch.setattr(monitor, "build_snapshot_view", Mock(return_value="view"))

    result = monitor.live_monitor(
        service,
        monotonic=monotonic,
        sleep=sleep,
        alert_engine=Mock(active_alerts=()),
    )

    assert result is None
    service.sample.assert_called_once_with()
    assert sleep.call_args.args[0] == pytest.approx(0.2)
    assert instances[0].updates == []
    assert instances[0].exited is True


def test_keyboard_interrupt_during_initial_sample_does_not_open_live_display(monkeypatch):
    service = _service(1.0, [KeyboardInterrupt])
    instances = _capture_live(monkeypatch)

    result = monitor.live_monitor(
        service,
        monotonic=Mock(),
        sleep=Mock(),
        alert_engine=Mock(active_alerts=()),
    )

    assert result is None
    assert instances == []
