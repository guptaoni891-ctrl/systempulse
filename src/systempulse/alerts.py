from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from systempulse.config import AlertRuleConfig, AlertsConfig
from systempulse.models import (
    ActiveAlert,
    AlertEvent,
    AlertSeverity,
    AlertTransition,
    SystemSnapshot,
)

MonotonicClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class _Observation:
    metric: str
    label: str
    value: float
    unit: str
    rule: AlertRuleConfig


@dataclass(slots=True)
class _MetricState:
    metric: str
    label: str
    unit: str
    severity: AlertSeverity = AlertSeverity.NORMAL
    current_value: float = 0.0
    threshold: float = 0.0
    pending_since: float | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    cooldown_until: float = 0.0


class AlertEngine:
    """Evaluate snapshots into state transitions without collecting metrics."""

    def __init__(
        self,
        config: AlertsConfig,
        *,
        monotonic: MonotonicClock | None = None,
    ) -> None:
        self.config = config
        self._monotonic = monotonic or time.monotonic
        self._states: dict[str, _MetricState] = {}
        self._history: deque[AlertEvent] = deque(maxlen=config.history_limit)

    @property
    def active_alerts(self) -> tuple[ActiveAlert, ...]:
        alerts = []
        for state in self._states.values():
            if (
                state.severity is AlertSeverity.NORMAL
                or state.opened_at is None
                or state.updated_at is None
            ):
                continue
            alerts.append(
                ActiveAlert(
                    metric=state.metric,
                    label=state.label,
                    severity=state.severity,
                    current_value=state.current_value,
                    threshold=state.threshold,
                    unit=state.unit,
                    opened_at=state.opened_at,
                    updated_at=state.updated_at,
                )
            )
        return tuple(sorted(alerts, key=lambda alert: alert.metric))

    def recent_events(self, limit: int | None = None) -> tuple[AlertEvent, ...]:
        events = tuple(self._history)
        if limit is None:
            return events
        if limit <= 0:
            return ()
        return events[-limit:]

    def evaluate(self, snapshot: SystemSnapshot) -> tuple[AlertEvent, ...]:
        if not self.config.enabled:
            return ()

        now = self._monotonic()
        events: list[AlertEvent] = []
        observed_metrics: set[str] = set()
        for observation in self._observations(snapshot):
            observed_metrics.add(observation.metric)
            event = self._evaluate_observation(observation, snapshot.timestamp, now)
            if event is not None:
                self._history.append(event)
                events.append(event)

        for metric, state in self._states.items():
            if metric not in observed_metrics and state.severity is AlertSeverity.NORMAL:
                state.pending_since = None

        return tuple(events)

    def _observations(self, snapshot: SystemSnapshot) -> Iterable[_Observation]:
        rules = self.config
        core_values = (
            ("cpu.usage", "CPU usage", snapshot.cpu_usage_percent, "%", rules.cpu),
            (
                "memory.usage",
                "Memory usage",
                snapshot.ram_usage_percent,
                "%",
                rules.memory,
            ),
            ("disk.usage", "Disk usage", snapshot.disk_usage_percent, "%", rules.disk),
        )
        for metric, label, value, unit, rule in core_values:
            if rule.enabled:
                yield _Observation(metric, label, float(value), unit, rule)

        if snapshot.cpu_temperature_celsius is not None and rules.cpu_temperature.enabled:
            yield _Observation(
                "cpu.temperature",
                "CPU temperature",
                float(snapshot.cpu_temperature_celsius),
                "°C",
                rules.cpu_temperature,
            )

        for index, gpu in enumerate(snapshot.gpus):
            if rules.gpu_usage.enabled:
                yield _Observation(
                    f"gpu.{index}.usage",
                    f"GPU {index} ({gpu.name}) usage",
                    float(gpu.usage_percent),
                    "%",
                    rules.gpu_usage,
                )
            if rules.gpu_temperature.enabled:
                yield _Observation(
                    f"gpu.{index}.temperature",
                    f"GPU {index} ({gpu.name}) temperature",
                    float(gpu.temperature_celsius),
                    "°C",
                    rules.gpu_temperature,
                )

    def _evaluate_observation(
        self,
        observation: _Observation,
        timestamp: datetime,
        now: float,
    ) -> AlertEvent | None:
        state = self._states.setdefault(
            observation.metric,
            _MetricState(
                metric=observation.metric,
                label=observation.label,
                unit=observation.unit,
            ),
        )
        state.label = observation.label
        state.unit = observation.unit
        state.current_value = observation.value
        state.updated_at = timestamp

        if state.severity is AlertSeverity.NORMAL:
            return self._evaluate_inactive(state, observation, timestamp, now)
        return self._evaluate_active(state, observation, timestamp, now)

    def _evaluate_inactive(
        self,
        state: _MetricState,
        observation: _Observation,
        timestamp: datetime,
        now: float,
    ) -> AlertEvent | None:
        target = _entry_severity(observation.value, observation.rule)
        if target is AlertSeverity.NORMAL:
            state.pending_since = None
            return None

        if state.pending_since is None:
            state.pending_since = now
        if now - state.pending_since < observation.rule.duration:
            return None
        if now < state.cooldown_until:
            return None

        state.severity = target
        state.threshold = _entry_threshold(target, observation.rule)
        state.opened_at = timestamp
        state.pending_since = None
        return self._event(state, AlertTransition.OPENED, timestamp)

    def _evaluate_active(
        self,
        state: _MetricState,
        observation: _Observation,
        timestamp: datetime,
        now: float,
    ) -> AlertEvent | None:
        target = _active_severity(state.severity, observation.value, observation.rule)
        if target is state.severity:
            return None

        if target is AlertSeverity.CRITICAL:
            state.severity = target
            state.threshold = observation.rule.critical
            return self._event(state, AlertTransition.ESCALATED, timestamp)

        if target is AlertSeverity.WARNING:
            state.severity = target
            state.threshold = observation.rule.warning
            return self._event(
                state,
                AlertTransition.DEESCALATED,
                timestamp,
                threshold=observation.rule.critical - observation.rule.hysteresis,
            )

        recovery_threshold = observation.rule.warning - observation.rule.hysteresis
        event = self._event(
            state,
            AlertTransition.RESOLVED,
            timestamp,
            severity=AlertSeverity.NORMAL,
            threshold=recovery_threshold,
        )
        state.severity = AlertSeverity.NORMAL
        state.threshold = 0.0
        state.opened_at = None
        state.pending_since = None
        state.cooldown_until = now + observation.rule.cooldown
        return event

    def _event(
        self,
        state: _MetricState,
        transition: AlertTransition,
        timestamp: datetime,
        *,
        severity: AlertSeverity | None = None,
        threshold: float | None = None,
    ) -> AlertEvent:
        event_severity = severity or state.severity
        event_threshold = state.threshold if threshold is None else threshold
        message = _message(
            state.label,
            transition,
            event_severity,
            state.current_value,
            event_threshold,
            state.unit,
        )
        return AlertEvent(
            timestamp=timestamp,
            metric=state.metric,
            label=state.label,
            severity=event_severity,
            transition=transition,
            current_value=state.current_value,
            threshold=event_threshold,
            unit=state.unit,
            message=message,
        )


def _entry_severity(value: float, rule: AlertRuleConfig) -> AlertSeverity:
    if value >= rule.critical:
        return AlertSeverity.CRITICAL
    if value >= rule.warning:
        return AlertSeverity.WARNING
    return AlertSeverity.NORMAL


def _entry_threshold(severity: AlertSeverity, rule: AlertRuleConfig) -> float:
    return rule.critical if severity is AlertSeverity.CRITICAL else rule.warning


def _active_severity(
    current: AlertSeverity,
    value: float,
    rule: AlertRuleConfig,
) -> AlertSeverity:
    if current is AlertSeverity.WARNING:
        if value >= rule.critical:
            return AlertSeverity.CRITICAL
        if value < rule.warning - rule.hysteresis:
            return AlertSeverity.NORMAL
        return AlertSeverity.WARNING

    if value >= rule.critical - rule.hysteresis:
        return AlertSeverity.CRITICAL
    if value >= rule.warning - rule.hysteresis:
        return AlertSeverity.WARNING
    return AlertSeverity.NORMAL


def _message(
    label: str,
    transition: AlertTransition,
    severity: AlertSeverity,
    value: float,
    threshold: float,
    unit: str,
) -> str:
    current = f"{value:.1f}{unit}"
    boundary = f"{threshold:.1f}{unit}"
    if transition is AlertTransition.OPENED:
        return f"{label} entered {severity.value} state: {current} >= {boundary}"
    if transition is AlertTransition.ESCALATED:
        return f"{label} escalated to critical: {current} >= {boundary}"
    if transition is AlertTransition.DEESCALATED:
        return f"{label} de-escalated to warning: {current}"
    return f"{label} recovered: {current}"
