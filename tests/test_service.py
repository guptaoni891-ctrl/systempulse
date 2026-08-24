from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock, call

import pytest

from systempulse.config import AppConfig
from systempulse.models import (
    CollectionDiagnostic,
    CoreMetrics,
    DiagnosticKind,
    GPUCollection,
    GPUStats,
    NetworkStats,
)
from systempulse.service import MonitorService


def _core(
    *,
    sent=1_000,
    received=2_000,
    temperature=61.5,
    diagnostics=(),
):
    return CoreMetrics(
        cpu_usage_percent=12.5,
        ram_usage_percent=50.0,
        ram_used_bytes=4_000,
        ram_total_bytes=8_000,
        disk_usage_percent=40.0,
        disk_used_bytes=40_000,
        disk_total_bytes=100_000,
        cpu_temperature_celsius=temperature,
        network=NetworkStats(bytes_sent=sent, bytes_received=received),
        diagnostics=tuple(diagnostics),
    )


def _gpu(name="Test GPU"):
    return GPUStats(
        name=name,
        usage_percent=25.0,
        temperature_celsius=55.0,
        vram_used_mib=512.0,
        vram_total_mib=4_096.0,
        power_watts=42.5,
    )


def _service(core_collector, **kwargs):
    return MonitorService(
        AppConfig(),
        core_collector=core_collector,
        gpu_collector=kwargs.pop(
            "gpu_collector", Mock(return_value=GPUCollection(gpus=()))
        ),
        monotonic=kwargs.pop("monotonic", Mock(return_value=10.0)),
        wall_clock=kwargs.pop(
            "wall_clock",
            Mock(return_value=datetime(2026, 8, 24, 8, 0, tzinfo=UTC)),
        ),
        **kwargs,
    )


def test_complete_sample_is_one_authoritative_immutable_representation():
    core_collector = Mock(return_value=_core())
    gpu_collector = Mock(return_value=GPUCollection(gpus=(_gpu("GPU One"), _gpu("GPU Two"))))
    service = _service(core_collector, gpu_collector=gpu_collector)

    sample = service.sample()

    assert sample.timestamp == datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    assert sample.cpu_usage_percent == 12.5
    assert sample.ram_used_bytes == 4_000
    assert sample.disk_used_bytes == 40_000
    assert sample.cpu_temperature_celsius == 61.5
    assert sample.network == NetworkStats(1_000, 2_000)
    assert sample.network_speed.upload_bytes_per_second == 0
    assert [gpu.name for gpu in sample.gpus] == ["GPU One", "GPU Two"]
    assert sample.diagnostics == ()
    core_collector.assert_called_once_with(service.config)
    gpu_collector.assert_called_once_with()


def test_first_sample_has_clean_zero_network_rates():
    sample = _service(Mock(return_value=_core())).sample()

    assert sample.network_speed.upload_bytes_per_second == 0
    assert sample.network_speed.download_bytes_per_second == 0
    assert not any(item.collector == "network_rate" for item in sample.diagnostics)


def test_subsequent_sample_uses_monotonic_elapsed_time_for_rates():
    core_collector = Mock(
        side_effect=[
            _core(sent=1_000, received=2_000),
            _core(sent=3_000, received=7_000),
        ]
    )
    service = _service(
        core_collector,
        monotonic=Mock(side_effect=[10.0, 12.0]),
        wall_clock=Mock(
            side_effect=[
                datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
                datetime(2030, 1, 1, tzinfo=UTC),
            ]
        ),
    )

    service.sample()
    sample = service.sample()

    assert sample.network_speed.upload_bytes_per_second == 1_000
    assert sample.network_speed.download_bytes_per_second == 2_500


def test_zero_elapsed_time_produces_zero_rates_and_diagnostic():
    core_collector = Mock(
        side_effect=[
            _core(sent=1_000, received=2_000),
            _core(sent=3_000, received=7_000),
        ]
    )
    service = _service(core_collector, monotonic=Mock(side_effect=[10.0, 10.0]))

    service.sample()
    sample = service.sample()

    assert sample.network_speed.upload_bytes_per_second == 0
    assert sample.network_speed.download_bytes_per_second == 0
    diagnostic = sample.diagnostics[-1]
    assert diagnostic.collector == "network_rate"
    assert diagnostic.kind is DiagnosticKind.INVALID_INTERVAL


def test_network_counter_reset_never_produces_negative_rates():
    core_collector = Mock(
        side_effect=[
            _core(sent=5_000, received=8_000),
            _core(sent=100, received=200),
        ]
    )
    service = _service(core_collector, monotonic=Mock(side_effect=[10.0, 12.0]))

    service.sample()
    sample = service.sample()

    assert sample.network_speed.upload_bytes_per_second == 0
    assert sample.network_speed.download_bytes_per_second == 0


def test_optional_collector_diagnostics_are_preserved_with_usable_sample():
    temperature_diagnostic = CollectionDiagnostic(
        collector="cpu_temperature",
        kind=DiagnosticKind.UNAVAILABLE,
        message="No sensor.",
    )
    gpu_diagnostic = CollectionDiagnostic(
        collector="gpu",
        kind=DiagnosticKind.COMMAND_MISSING,
        message="No nvidia-smi.",
    )
    service = _service(
        Mock(return_value=_core(temperature=None, diagnostics=(temperature_diagnostic,))),
        gpu_collector=Mock(
            return_value=GPUCollection(gpus=(), diagnostics=(gpu_diagnostic,))
        ),
    )

    sample = service.sample()

    assert sample.cpu_temperature_celsius is None
    assert sample.gpus == ()
    assert sample.diagnostics == (temperature_diagnostic, gpu_diagnostic)
    assert sample.cpu_usage_percent == 12.5


def test_disabled_gpu_is_not_polled_or_reported_as_failure():
    gpu_collector = Mock()
    service = _service(
        Mock(return_value=_core()),
        include_gpu=False,
        gpu_collector=gpu_collector,
    )

    sample = service.sample()

    assert sample.gpus == ()
    assert sample.diagnostics == ()
    gpu_collector.assert_not_called()


def test_sample_with_network_rate_primes_only_counters_before_complete_sample():
    core_collector = Mock(return_value=_core(sent=3_000, received=7_000))
    gpu_collector = Mock(return_value=GPUCollection(gpus=(_gpu(),)))
    network_collector = Mock(return_value=NetworkStats(1_000, 2_000))
    sleep = Mock()
    service = _service(
        core_collector,
        gpu_collector=gpu_collector,
        network_collector=network_collector,
        monotonic=Mock(side_effect=[10.0, 12.0]),
        sleep=sleep,
    )

    sample = service.sample_with_network_rate(interval=1.0)

    assert sample.network_speed.upload_bytes_per_second == 1_000
    assert sample.network_speed.download_bytes_per_second == 2_500
    network_collector.assert_called_once_with()
    sleep.assert_called_once_with(1.0)
    core_collector.assert_called_once_with(service.config)
    gpu_collector.assert_called_once_with()


def test_sample_with_network_rate_reuses_existing_previous_sample():
    core_collector = Mock(
        side_effect=[
            _core(sent=1_000, received=2_000),
            _core(sent=3_000, received=6_000),
        ]
    )
    network_collector = Mock()
    sleep = Mock()
    service = _service(
        core_collector,
        network_collector=network_collector,
        monotonic=Mock(side_effect=[10.0, 12.0]),
        sleep=sleep,
    )

    service.sample()
    sample = service.sample_with_network_rate()

    assert sample.network_speed.upload_bytes_per_second == 1_000
    assert sample.network_speed.download_bytes_per_second == 2_000
    network_collector.assert_not_called()
    sleep.assert_called_once_with(1.0)


def test_timestamp_is_normalized_to_utc():
    offset = timezone(timedelta(hours=4))
    service = _service(
        Mock(return_value=_core()),
        wall_clock=Mock(return_value=datetime(2026, 8, 24, 12, 0, tzinfo=offset)),
    )

    sample = service.sample()

    assert sample.timestamp == datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    assert sample.timestamp.tzinfo is UTC


def test_naive_wall_clock_is_rejected():
    service = _service(
        Mock(return_value=_core()),
        wall_clock=Mock(return_value=datetime(2026, 8, 24, 8, 0)),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        service.sample()


def test_service_calls_each_complete_collector_once_per_sample():
    core_collector = Mock(return_value=_core())
    gpu_collector = Mock(return_value=GPUCollection(gpus=()))
    service = _service(core_collector, gpu_collector=gpu_collector)

    service.sample()

    assert core_collector.mock_calls == [call(service.config)]
    assert gpu_collector.mock_calls == [call()]
