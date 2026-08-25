import builtins
import threading
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from prometheus_client import CollectorRegistry, generate_latest

import systempulse.exporter as exporter
from systempulse.models import GPUStats, NetworkSpeed, NetworkStats, SystemSnapshot


def _gpu(index=0, *, power=42.5):
    return GPUStats(
        name=f"GPU {index}",
        usage_percent=25.0 + index,
        temperature_celsius=55.0 + index,
        vram_used_mib=512.0 + index,
        vram_total_mib=4_096.0,
        power_watts=power,
    )


def _snapshot(*, temperature=61.5, gpus=(), sent=1_000, received=2_000):
    return SystemSnapshot(
        timestamp=datetime(2026, 8, 25, 8, 0, tzinfo=UTC),
        cpu_usage_percent=12.5,
        ram_usage_percent=50.0,
        ram_used_bytes=4_000,
        ram_total_bytes=8_000,
        disk_usage_percent=40.0,
        disk_used_bytes=40_000,
        disk_total_bytes=100_000,
        cpu_temperature_celsius=temperature,
        network=NetworkStats(sent, received),
        network_speed=NetworkSpeed(125.0, 250.0),
        gpus=tuple(gpus),
    )


def _registry(snapshot=None, *, now=15.0, sampled_at=10.0):
    state = exporter.ExporterState()
    if snapshot is not None:
        state.record_success(snapshot, sampled_at)
    return state, exporter.create_registry(state, monotonic=Mock(return_value=now))


def _samples(registry):
    return {
        (sample.name, tuple(sorted(sample.labels.items()))): sample.value
        for metric in registry.collect()
        for sample in metric.samples
    }


def _text(registry):
    return generate_latest(registry).decode("utf-8")


def test_registry_is_dedicated_and_contains_only_systempulse_metrics():
    _, registry = _registry()

    names = {sample.name for metric in registry.collect() for sample in metric.samples}

    assert isinstance(registry, CollectorRegistry)
    assert names == {"systempulse_up", "systempulse_sampling_errors_total"}
    assert "python_info" not in _text(registry)
    assert "process_" not in _text(registry)


def test_separate_registries_do_not_duplicate_registration():
    first = exporter.create_registry(exporter.ExporterState())
    second = exporter.create_registry(exporter.ExporterState())

    assert first is not second
    assert _text(first).count("# TYPE systempulse_up gauge") == 1
    assert _text(second).count("# TYPE systempulse_up gauge") == 1


def test_health_before_first_sample_has_no_core_metrics():
    _, registry = _registry()
    samples = _samples(registry)

    assert samples[("systempulse_up", ())] == 0
    assert samples[("systempulse_sampling_errors_total", ())] == 0
    assert not any(name == "systempulse_cpu_usage_ratio" for name, _ in samples)


def test_core_values_convert_percentages_to_ratios_and_preserve_bytes():
    _, registry = _registry(_snapshot())
    samples = _samples(registry)

    assert samples[("systempulse_cpu_usage_ratio", ())] == 0.125
    assert samples[("systempulse_memory_usage_ratio", ())] == 0.5
    assert samples[("systempulse_disk_usage_ratio", ())] == 0.4
    assert samples[("systempulse_memory_used_bytes", ())] == 4_000
    assert samples[("systempulse_memory_total_bytes", ())] == 8_000
    assert samples[("systempulse_disk_used_bytes", ())] == 40_000
    assert samples[("systempulse_disk_total_bytes", ())] == 100_000


def test_temperature_is_exported_when_available():
    _, registry = _registry(_snapshot(temperature=61.5))

    assert _samples(registry)[("systempulse_cpu_temperature_celsius", ())] == 61.5


def test_temperature_is_omitted_when_unavailable():
    _, registry = _registry(_snapshot(temperature=None))

    assert "systempulse_cpu_temperature_celsius" not in _text(registry)


def test_network_os_counters_are_external_counter_families_and_rates_are_gauges():
    _, registry = _registry(_snapshot(sent=10_000, received=20_000))
    samples = _samples(registry)
    text = _text(registry)

    assert samples[("systempulse_network_bytes_sent_total", ())] == 10_000
    assert samples[("systempulse_network_bytes_received_total", ())] == 20_000
    assert samples[("systempulse_network_upload_bytes_per_second", ())] == 125
    assert samples[("systempulse_network_download_bytes_per_second", ())] == 250
    assert "# TYPE systempulse_network_bytes_sent_total counter" in text
    assert "# TYPE systempulse_network_upload_bytes_per_second gauge" in text


def test_first_network_sample_exposes_zero_rates_without_hiding_counters():
    snapshot = _snapshot()
    snapshot = SystemSnapshot(
        **{
            field: getattr(snapshot, field)
            for field in snapshot.__dataclass_fields__
            if field != "network_speed"
        },
        network_speed=NetworkSpeed(0.0, 0.0),
    )
    _, registry = _registry(snapshot)
    samples = _samples(registry)

    assert samples[("systempulse_network_bytes_sent_total", ())] == 1_000
    assert samples[("systempulse_network_upload_bytes_per_second", ())] == 0


def test_network_counter_reset_is_exposed_without_crashing_or_accumulating_locally():
    state, registry = _registry(_snapshot(sent=10_000, received=20_000))
    state.record_success(_snapshot(sent=50, received=100), 20.0)

    samples = _samples(registry)

    assert samples[("systempulse_network_bytes_sent_total", ())] == 50
    assert samples[("systempulse_network_bytes_received_total", ())] == 100


def test_zero_gpus_omits_gpu_metric_families():
    _, registry = _registry(_snapshot(gpus=()))

    assert "systempulse_gpu_" not in _text(registry)


def test_one_gpu_uses_bounded_index_label_and_base_units():
    _, registry = _registry(_snapshot(gpus=(_gpu(),)))
    samples = _samples(registry)
    label = (("gpu", "0"),)

    assert samples[("systempulse_gpu_usage_ratio", label)] == 0.25
    assert samples[("systempulse_gpu_temperature_celsius", label)] == 55
    assert samples[("systempulse_gpu_memory_used_bytes", label)] == 512 * 1024 * 1024
    assert samples[("systempulse_gpu_memory_total_bytes", label)] == 4096 * 1024 * 1024
    assert samples[("systempulse_gpu_power_watts", label)] == 42.5


def test_multiple_gpus_share_metric_names_with_stable_index_labels():
    _, registry = _registry(_snapshot(gpus=(_gpu(0), _gpu(1))))
    samples = _samples(registry)

    labels = {
        labels
        for (name, labels) in samples
        if name == "systempulse_gpu_usage_ratio"
    }
    assert labels == {(("gpu", "0"),), (("gpu", "1"),)}
    assert "gpu_0" not in _text(registry)
    assert "GPU 0" not in _text(registry)


def test_nullable_gpu_power_omits_only_that_gpu_power_series():
    _, registry = _registry(_snapshot(gpus=(_gpu(0, power=None), _gpu(1))))
    samples = _samples(registry)

    assert ("systempulse_gpu_power_watts", (("gpu", "0"),)) not in samples
    assert samples[("systempulse_gpu_power_watts", (("gpu", "1"),))] == 42.5


def test_latest_snapshot_replacement_removes_disappearing_gpu_series():
    state, registry = _registry(_snapshot(gpus=(_gpu(),)))
    assert 'gpu="0"' in _text(registry)

    state.record_success(_snapshot(gpus=()), 20.0)

    assert "systempulse_gpu_" not in _text(registry)


def test_exposition_has_help_and_type_metadata_and_no_per_process_metrics():
    _, registry = _registry(_snapshot(gpus=(_gpu(),)))
    text = _text(registry)

    assert "# HELP systempulse_cpu_usage_ratio" in text
    assert "# TYPE systempulse_cpu_usage_ratio gauge" in text
    assert "systempulse_process" not in text


def test_sample_timestamp_and_monotonic_age_have_precise_semantics():
    snapshot = _snapshot()
    _, registry = _registry(snapshot, now=14.5, sampled_at=10.0)
    samples = _samples(registry)

    assert samples[("systempulse_last_sample_timestamp_seconds", ())] == pytest.approx(
        snapshot.timestamp.timestamp()
    )
    assert samples[("systempulse_sample_age_seconds", ())] == 4.5


def test_failed_attempt_retains_sample_marks_down_and_increments_errors():
    state, registry = _registry(_snapshot(), now=15.0, sampled_at=10.0)

    state.record_failure()
    samples = _samples(registry)

    assert samples[("systempulse_up", ())] == 0
    assert samples[("systempulse_sampling_errors_total", ())] == 1
    assert samples[("systempulse_cpu_usage_ratio", ())] == 0.125
    assert samples[("systempulse_sample_age_seconds", ())] == 5


def test_success_after_failure_restores_health_without_resetting_error_counter():
    state, registry = _registry()
    state.record_failure()
    state.record_success(_snapshot(), 10.0)

    samples = _samples(registry)

    assert samples[("systempulse_up", ())] == 1
    assert samples[("systempulse_sampling_errors_total", ())] == 1


def test_scrapes_never_invoke_monitor_service_even_when_repeated():
    service = Mock()
    _, registry = _registry(_snapshot())

    generate_latest(registry)
    generate_latest(registry)
    generate_latest(registry)

    service.sample.assert_not_called()


class _ControlledStop:
    def __init__(self, stop_after):
        self.stop_after = stop_after
        self.delays = []

    def is_set(self):
        return False

    def wait(self, delay):
        self.delays.append(delay)
        return len(self.delays) >= self.stop_after


def test_sampling_loop_samples_immediately_and_at_configured_cadence():
    service = Mock()
    service.sample.side_effect = [_snapshot(sent=1), _snapshot(sent=2)]
    state = exporter.ExporterState()
    stop = _ControlledStop(2)
    clock = Mock(side_effect=[0.0, 0.0, 0.0, 5.0, 5.0])

    exporter.run_sampling_loop(service, state, 5.0, stop, monotonic=clock)

    assert service.sample.call_count == 2
    assert stop.delays == [5.0, 5.0]
    assert state.read().snapshot.network.bytes_sent == 2


def test_sampling_loop_skips_missed_ticks_after_slow_sample():
    service = Mock(return_value=None)
    service.sample.return_value = _snapshot()
    state = exporter.ExporterState()
    stop = _ControlledStop(1)
    clock = Mock(side_effect=[0.0, 7.0, 7.0])

    exporter.run_sampling_loop(service, state, 5.0, stop, monotonic=clock)

    assert stop.delays == [3.0]


def test_sampling_loop_survives_recoverable_failure_with_previous_sample():
    service = Mock()
    service.sample.side_effect = [_snapshot(), OSError("temporary failure")]
    state = exporter.ExporterState()
    stop = _ControlledStop(2)
    clock = Mock(side_effect=[0.0, 0.0, 0.0, 5.0])

    exporter.run_sampling_loop(service, state, 5.0, stop, monotonic=clock)

    view = state.read()
    assert view.snapshot is not None
    assert view.up is False
    assert view.sampling_errors == 1


def test_state_supports_concurrent_atomic_replacement_and_reads():
    state = exporter.ExporterState()
    errors = []

    def writer():
        for value in range(500):
            state.record_success(_snapshot(sent=value), float(value))

    def reader():
        for _ in range(500):
            view = state.read()
            if view.snapshot is not None and view.successful_sample_monotonic is None:
                errors.append(view)

    threads = [
        threading.Thread(target=writer),
        *(threading.Thread(target=reader) for _ in range(3)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert state.read().snapshot.network.bytes_sent == 499


def test_server_startup_socket_error_is_wrapped(monkeypatch):
    from prometheus_client import CollectorRegistry as Registry
    from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

    start = Mock(side_effect=OSError("address in use"))
    monkeypatch.setattr(
        exporter,
        "_load_prometheus",
        Mock(return_value=(Registry, start, CounterMetricFamily, GaugeMetricFamily)),
    )

    with pytest.raises(exporter.ExporterError, match="127.0.0.1:9100.*address in use"):
        exporter.serve_exporter(Mock(), host="127.0.0.1", port=9100, interval=5.0)


def test_ctrl_c_stops_sampler_and_closes_http_server(monkeypatch):
    from prometheus_client import CollectorRegistry as Registry
    from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

    http_server = Mock()
    server_thread = Mock()
    server_thread.is_alive.return_value = True
    start = Mock(return_value=(http_server, server_thread))
    monkeypatch.setattr(
        exporter,
        "_load_prometheus",
        Mock(return_value=(Registry, start, CounterMetricFamily, GaugeMetricFamily)),
    )
    monkeypatch.setattr(
        exporter,
        "_wait_for_sampling_thread",
        Mock(side_effect=KeyboardInterrupt),
    )

    exporter.serve_exporter(
        Mock(sample=Mock(return_value=_snapshot())),
        host="127.0.0.1",
        port=9100,
        interval=5.0,
    )

    http_server.shutdown.assert_called_once_with()
    http_server.server_close.assert_called_once_with()
    server_thread.join.assert_called_once_with(timeout=2.0)


def test_optional_dependency_error_is_friendly_and_actionable(monkeypatch):
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name.startswith("prometheus_client"):
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(exporter.PrometheusDependencyError) as error:
        exporter.create_registry(exporter.ExporterState())

    assert 'pip install "systempulse[prometheus]"' in str(error.value)
