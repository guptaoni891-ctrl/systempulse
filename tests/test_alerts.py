from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock

from systempulse.alerts import AlertEngine
from systempulse.config import AlertRuleConfig, AlertsConfig
from systempulse.models import (
    AlertSeverity,
    AlertTransition,
    GPUStats,
    NetworkSpeed,
    NetworkStats,
    SystemSnapshot,
)


def _disabled_rule():
    return AlertRuleConfig(60, 80, enabled=False)


def _alerts(
    *,
    cpu=None,
    memory=None,
    disk=None,
    cpu_temperature=None,
    gpu_usage=None,
    gpu_temperature=None,
    history_limit=100,
):
    return AlertsConfig(
        history_limit=history_limit,
        cpu=cpu or _disabled_rule(),
        memory=memory or _disabled_rule(),
        disk=disk or _disabled_rule(),
        cpu_temperature=cpu_temperature or _disabled_rule(),
        gpu_usage=gpu_usage or _disabled_rule(),
        gpu_temperature=gpu_temperature or _disabled_rule(),
    )


def _snapshot(
    *,
    cpu=20.0,
    memory=20.0,
    disk=20.0,
    temperature=None,
    gpus=(),
    timestamp=None,
):
    return SystemSnapshot(
        timestamp=timestamp or datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        cpu_usage_percent=cpu,
        ram_usage_percent=memory,
        ram_used_bytes=2_000,
        ram_total_bytes=10_000,
        disk_usage_percent=disk,
        disk_used_bytes=2_000,
        disk_total_bytes=10_000,
        cpu_temperature_celsius=temperature,
        network=NetworkStats(1_000, 2_000),
        network_speed=NetworkSpeed(0.0, 0.0),
        gpus=tuple(gpus),
    )


def _gpu(name, usage, temperature=40.0):
    return GPUStats(name, usage, temperature, 100.0, 1_000.0, None)


def test_global_disable_skips_evaluation_and_clock():
    clock = Mock()
    engine = AlertEngine(AlertsConfig(enabled=False), monotonic=clock)

    assert engine.evaluate(_snapshot(cpu=100)) == ()
    assert engine.active_alerts == ()
    clock.assert_not_called()


def test_individual_rule_disable_skips_metric():
    engine = AlertEngine(_alerts(cpu=_disabled_rule()), monotonic=Mock(return_value=0.0))

    assert engine.evaluate(_snapshot(cpu=100)) == ()


def test_memory_and_disk_rules_are_evaluated_independently():
    engine = AlertEngine(
        _alerts(
            memory=AlertRuleConfig(60, 80),
            disk=AlertRuleConfig(70, 90),
        ),
        monotonic=Mock(return_value=0.0),
    )

    events = engine.evaluate(_snapshot(memory=65, disk=95))

    assert [(event.metric, event.severity) for event in events] == [
        ("memory.usage", AlertSeverity.WARNING),
        ("disk.usage", AlertSeverity.CRITICAL),
    ]


def test_normal_to_warning_opens_one_deterministic_event():
    rule = AlertRuleConfig(60, 80, cooldown=0)
    engine = AlertEngine(_alerts(cpu=rule), monotonic=Mock(return_value=0.0))

    events = engine.evaluate(_snapshot(cpu=64.2))

    assert len(events) == 1
    event = events[0]
    assert event.metric == "cpu.usage"
    assert event.severity is AlertSeverity.WARNING
    assert event.transition is AlertTransition.OPENED
    assert event.timestamp.tzinfo is UTC
    assert event.message == "CPU usage entered warning state: 64.2% >= 60.0%"


def test_normal_to_critical_is_opened_not_escalated():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80)),
        monotonic=Mock(return_value=0.0),
    )

    event = engine.evaluate(_snapshot(cpu=90))[0]

    assert event.severity is AlertSeverity.CRITICAL
    assert event.transition is AlertTransition.OPENED


def test_unchanged_active_state_suppresses_duplicate_events():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80)),
        monotonic=Mock(side_effect=[0.0, 1.0, 2.0]),
    )

    assert len(engine.evaluate(_snapshot(cpu=70))) == 1
    assert engine.evaluate(_snapshot(cpu=72)) == ()
    assert engine.evaluate(_snapshot(cpu=79)) == ()
    assert len(engine.recent_events()) == 1


def test_warning_escalates_to_critical():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80)),
        monotonic=Mock(side_effect=[0.0, 1.0]),
    )
    engine.evaluate(_snapshot(cpu=65))

    event = engine.evaluate(_snapshot(cpu=85))[0]

    assert event.transition is AlertTransition.ESCALATED
    assert event.severity is AlertSeverity.CRITICAL


def test_critical_deescalates_only_below_hysteresis_boundary():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80, hysteresis=5)),
        monotonic=Mock(side_effect=[0.0, 1.0, 2.0]),
    )
    engine.evaluate(_snapshot(cpu=85))

    assert engine.evaluate(_snapshot(cpu=76)) == ()
    event = engine.evaluate(_snapshot(cpu=74.9))[0]

    assert event.transition is AlertTransition.DEESCALATED
    assert event.severity is AlertSeverity.WARNING


def test_warning_resolves_only_below_hysteresis_boundary():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80, hysteresis=5)),
        monotonic=Mock(side_effect=[0.0, 1.0, 2.0, 3.0]),
    )
    engine.evaluate(_snapshot(cpu=65))

    assert engine.evaluate(_snapshot(cpu=59)) == ()
    assert engine.evaluate(_snapshot(cpu=55)) == ()
    event = engine.evaluate(_snapshot(cpu=54.9))[0]

    assert event.transition is AlertTransition.RESOLVED
    assert event.severity is AlertSeverity.NORMAL
    assert engine.active_alerts == ()


def test_critical_can_resolve_directly_to_normal():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80, hysteresis=5)),
        monotonic=Mock(side_effect=[0.0, 1.0]),
    )
    engine.evaluate(_snapshot(cpu=85))

    event = engine.evaluate(_snapshot(cpu=40))[0]

    assert event.transition is AlertTransition.RESOLVED
    assert event.severity is AlertSeverity.NORMAL


def test_duration_requires_continuous_threshold_time():
    clock = Mock(side_effect=[0.0, 9.9, 10.0])
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80, duration=10)),
        monotonic=clock,
    )

    assert engine.evaluate(_snapshot(cpu=65)) == ()
    assert engine.evaluate(_snapshot(cpu=65)) == ()
    event = engine.evaluate(_snapshot(cpu=65))[0]

    assert event.transition is AlertTransition.OPENED


def test_escalation_while_pending_does_not_restart_duration():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80, duration=10)),
        monotonic=Mock(side_effect=[0.0, 5.0, 10.0]),
    )

    assert engine.evaluate(_snapshot(cpu=65)) == ()
    assert engine.evaluate(_snapshot(cpu=90)) == ()
    event = engine.evaluate(_snapshot(cpu=90))[0]

    assert event.severity is AlertSeverity.CRITICAL
    assert event.transition is AlertTransition.OPENED


def test_recovery_before_duration_cancels_pending_alert():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80, duration=10)),
        monotonic=Mock(side_effect=[0.0, 5.0, 11.0, 20.9, 21.0]),
    )

    assert engine.evaluate(_snapshot(cpu=65)) == ()
    assert engine.evaluate(_snapshot(cpu=40)) == ()
    assert engine.evaluate(_snapshot(cpu=65)) == ()
    assert engine.evaluate(_snapshot(cpu=65)) == ()
    assert len(engine.evaluate(_snapshot(cpu=65))) == 1


def test_cooldown_delays_reopening_after_resolution():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80, cooldown=10)),
        monotonic=Mock(side_effect=[0.0, 1.0, 5.0, 11.0]),
    )

    assert len(engine.evaluate(_snapshot(cpu=65))) == 1
    assert engine.evaluate(_snapshot(cpu=40))[0].transition is AlertTransition.RESOLVED
    assert engine.evaluate(_snapshot(cpu=65)) == ()
    assert engine.evaluate(_snapshot(cpu=65))[0].transition is AlertTransition.OPENED


def test_unavailable_metric_cancels_pending_duration():
    rule = AlertRuleConfig(60, 80, duration=10)
    engine = AlertEngine(
        _alerts(cpu_temperature=rule),
        monotonic=Mock(side_effect=[0.0, 5.0, 15.0, 24.9, 25.0]),
    )

    assert engine.evaluate(_snapshot(temperature=70)) == ()
    assert engine.evaluate(_snapshot(temperature=None)) == ()
    assert engine.evaluate(_snapshot(temperature=70)) == ()
    assert engine.evaluate(_snapshot(temperature=70)) == ()
    assert len(engine.evaluate(_snapshot(temperature=70))) == 1


def test_active_alert_is_held_when_metric_becomes_unavailable():
    engine = AlertEngine(
        _alerts(cpu_temperature=AlertRuleConfig(60, 80)),
        monotonic=Mock(side_effect=[0.0, 1.0]),
    )
    engine.evaluate(_snapshot(temperature=70))

    assert engine.evaluate(_snapshot(temperature=None)) == ()
    assert len(engine.active_alerts) == 1
    assert engine.active_alerts[0].current_value == 70


def test_gpu_unavailable_generates_no_alert():
    engine = AlertEngine(
        _alerts(gpu_usage=AlertRuleConfig(60, 80)),
        monotonic=Mock(return_value=0.0),
    )

    assert engine.evaluate(_snapshot(gpus=())) == ()
    assert engine.active_alerts == ()


def test_gpu_temperature_rule_is_evaluated_separately_from_usage():
    engine = AlertEngine(
        _alerts(gpu_temperature=AlertRuleConfig(70, 85)),
        monotonic=Mock(return_value=0.0),
    )

    event = engine.evaluate(_snapshot(gpus=(_gpu("Hot", 10, temperature=90),)))[0]

    assert event.metric == "gpu.0.temperature"
    assert event.severity is AlertSeverity.CRITICAL


def test_multiple_gpus_have_independent_bounded_identities():
    engine = AlertEngine(
        _alerts(gpu_usage=AlertRuleConfig(60, 80)),
        monotonic=Mock(return_value=0.0),
    )

    events = engine.evaluate(_snapshot(gpus=(_gpu("First", 70), _gpu("Second", 90))))

    assert [event.metric for event in events] == ["gpu.0.usage", "gpu.1.usage"]
    assert [event.severity for event in events] == [
        AlertSeverity.WARNING,
        AlertSeverity.CRITICAL,
    ]
    assert [alert.label for alert in engine.active_alerts] == [
        "GPU 0 (First) usage",
        "GPU 1 (Second) usage",
    ]


def test_event_history_is_bounded_and_supports_recent_limit():
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80, cooldown=0), history_limit=2),
        monotonic=Mock(side_effect=[0.0, 1.0, 2.0, 3.0]),
    )

    engine.evaluate(_snapshot(cpu=65))
    engine.evaluate(_snapshot(cpu=85))
    engine.evaluate(_snapshot(cpu=70))
    engine.evaluate(_snapshot(cpu=40))

    assert [event.transition for event in engine.recent_events()] == [
        AlertTransition.DEESCALATED,
        AlertTransition.RESOLVED,
    ]
    assert [event.transition for event in engine.recent_events(1)] == [AlertTransition.RESOLVED]
    assert engine.recent_events(0) == ()


def test_event_timestamps_are_normalized_to_utc():
    offset = timezone(timedelta(hours=4))
    engine = AlertEngine(
        _alerts(cpu=AlertRuleConfig(60, 80)),
        monotonic=Mock(return_value=0.0),
    )

    event = engine.evaluate(
        _snapshot(
            cpu=65,
            timestamp=datetime(2026, 8, 24, 12, 0, tzinfo=offset),
        )
    )[0]

    assert event.timestamp == datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    assert event.timestamp.tzinfo is UTC
