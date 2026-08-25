import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone

import pytest

import systempulse.history as history_module
from systempulse.history import (
    SCHEMA_VERSION,
    HistoryError,
    HistoryStore,
    UnsupportedSchemaVersionError,
)
from systempulse.models import (
    AlertEvent,
    AlertSeverity,
    AlertTransition,
    GPUStats,
    NetworkSpeed,
    NetworkStats,
    SystemSnapshot,
)


def _gpu(name="Test GPU", usage=25.0, temperature=55.0, power=42.5):
    return GPUStats(name, usage, temperature, 512.0, 4_096.0, power)


def _snapshot(
    *,
    timestamp=None,
    cpu=12.5,
    memory=50.0,
    disk=40.0,
    temperature=61.5,
    sent=1_000,
    received=2_000,
    upload=100.0,
    download=200.0,
    gpus=(),
):
    return SystemSnapshot(
        timestamp=timestamp or datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        cpu_usage_percent=cpu,
        ram_usage_percent=memory,
        ram_used_bytes=4_000,
        ram_total_bytes=8_000,
        disk_usage_percent=disk,
        disk_used_bytes=40_000,
        disk_total_bytes=100_000,
        cpu_temperature_celsius=temperature,
        network=NetworkStats(sent, received),
        network_speed=NetworkSpeed(upload, download),
        gpus=tuple(gpus),
    )


def _event(timestamp=None, *, metric="cpu.usage", transition=AlertTransition.OPENED):
    return AlertEvent(
        timestamp=timestamp or datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        metric=metric,
        label="CPU usage",
        severity=AlertSeverity.WARNING,
        transition=transition,
        current_value=70.0,
        threshold=60.0,
        unit="%",
        message="CPU usage entered warning state: 70.0% >= 60.0%",
    )


def _rows(path, sql, parameters=()):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql, parameters).fetchall()


def test_database_and_parent_directories_are_created_with_versioned_schema(tmp_path):
    path = tmp_path / "nested" / "history" / "systempulse.db"

    store = HistoryStore(path)

    assert path.is_file()
    assert store.schema_version() == SCHEMA_VERSION == 1
    tables = {
        row[0]
        for row in _rows(
            path,
            "SELECT name FROM sqlite_master WHERE type = ?",
            ("table",),
        )
    }
    assert {"snapshots", "gpu_samples", "alert_events"} <= tables
    indexes = {
        row[0]
        for row in _rows(
            path,
            "SELECT name FROM sqlite_master WHERE type = ?",
            ("index",),
        )
    }
    assert {
        "snapshots_timestamp_idx",
        "alert_events_timestamp_idx",
        "alert_events_metric_idx",
    } <= indexes


def test_future_schema_version_is_rejected(tmp_path):
    path = tmp_path / "future.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA user_version = 99")
        connection.commit()

    with pytest.raises(UnsupportedSchemaVersionError, match="schema version 99"):
        HistoryStore(path)


def test_incomplete_current_schema_is_rejected(tmp_path):
    path = tmp_path / "incomplete.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY)")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()

    with pytest.raises(HistoryError, match="incomplete version 1 schema"):
        HistoryStore(path)


def test_failed_initial_migration_rolls_back(monkeypatch, tmp_path):
    path = tmp_path / "failed-migration.db"
    monkeypatch.setattr(
        history_module,
        "_SCHEMA_STATEMENTS",
        ("CREATE TABLE temporary_table (id INTEGER)", "INVALID SQL"),
    )

    with pytest.raises(HistoryError, match="initialize history database"):
        HistoryStore(path)

    tables = _rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")
    assert tables == []
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0


def test_snapshot_insertion_preserves_numeric_fields_and_null_temperature(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)

    snapshot_id = store.record_sample(
        _snapshot(cpu=12.3456789, temperature=None, upload=123.456789)
    )

    row = _rows(
        path,
        """
        SELECT id, timestamp_utc, cpu_usage_percent, cpu_temperature_celsius,
               upload_bytes_per_second
        FROM snapshots
        """,
    )[0]
    assert row[0] == snapshot_id
    assert datetime.fromisoformat(row[1]).tzinfo is not None
    assert row[2] == pytest.approx(12.3456789)
    assert row[3] is None
    assert row[4] == pytest.approx(123.456789)


def test_zero_gpus_creates_no_gpu_rows(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)

    store.record_sample(_snapshot(gpus=()))

    assert _rows(path, "SELECT * FROM gpu_samples") == []


def test_one_gpu_is_associated_with_snapshot(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)

    snapshot_id = store.record_sample(_snapshot(gpus=(_gpu(power=None),)))

    row = _rows(
        path,
        "SELECT snapshot_id, gpu_index, name, power_watts FROM gpu_samples",
    )[0]
    assert row == (snapshot_id, 0, "Test GPU", None)


def test_multiple_gpus_use_deterministic_snapshot_indexes(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)

    snapshot_id = store.record_sample(
        _snapshot(gpus=(_gpu("First"), _gpu("Second", temperature=75)))
    )

    assert _rows(
        path,
        """
        SELECT snapshot_id, gpu_index, name, temperature_celsius
        FROM gpu_samples ORDER BY gpu_index
        """,
    ) == [
        (snapshot_id, 0, "First", 55.0),
        (snapshot_id, 1, "Second", 75.0),
    ]


def test_alert_events_are_persisted_and_reconstructed_as_domain_models(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    event = _event()

    snapshot_id = store.record_sample(_snapshot(), (event,))
    returned = store.recent_alert_events(limit=5)

    assert returned == (event,)
    assert _rows(path, "SELECT snapshot_id, metric FROM alert_events") == [
        (snapshot_id, "cpu.usage")
    ]


def test_snapshot_gpu_and_events_are_one_atomic_transaction(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_alert BEFORE INSERT ON alert_events
            BEGIN
                SELECT RAISE(ABORT, 'test failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(HistoryError, match="record a history sample"):
        store.record_sample(_snapshot(gpus=(_gpu(),)), (_event(),))

    assert _rows(path, "SELECT COUNT(*) FROM snapshots")[0][0] == 0
    assert _rows(path, "SELECT COUNT(*) FROM gpu_samples")[0][0] == 0
    assert _rows(path, "SELECT COUNT(*) FROM alert_events")[0][0] == 0


def test_summary_aggregates_metrics_temperatures_alerts_and_counter_change(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    start = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    store.record_sample(
        _snapshot(
            timestamp=start,
            cpu=10,
            memory=40,
            disk=30,
            temperature=None,
            sent=1_000,
            received=2_000,
            gpus=(_gpu(temperature=50),),
        )
    )
    store.record_sample(
        _snapshot(
            timestamp=start + timedelta(hours=1),
            cpu=30,
            memory=60,
            disk=50,
            temperature=80,
            sent=4_000,
            received=8_000,
            gpus=(_gpu(temperature=90),),
        ),
        (_event(start + timedelta(hours=1)),),
    )

    summary = store.query_summary()

    assert summary.period_start == start
    assert summary.period_end == start + timedelta(hours=1)
    assert summary.sample_count == 2
    assert summary.average_cpu_percent == 20
    assert summary.peak_cpu_percent == 30
    assert summary.average_memory_percent == 50
    assert summary.peak_memory_percent == 60
    assert summary.average_disk_percent == 40
    assert summary.peak_disk_percent == 50
    assert summary.peak_cpu_temperature_celsius == 80
    assert summary.peak_gpu_temperature_celsius == 90
    assert summary.observed_network_sent_change_bytes == 3_000
    assert summary.observed_network_received_change_bytes == 6_000
    assert summary.alert_event_count == 1


def test_summary_since_filter_excludes_older_samples_and_events(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    start = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    store.record_sample(_snapshot(timestamp=start, cpu=90), (_event(start),))
    store.record_sample(_snapshot(timestamp=start + timedelta(hours=2), cpu=20))

    summary = store.query_summary(since=start + timedelta(hours=1))

    assert summary.sample_count == 1
    assert summary.average_cpu_percent == 20
    assert summary.alert_event_count == 0
    assert summary.observed_network_sent_change_bytes is None


def test_empty_summary_uses_none_instead_of_fake_values(tmp_path):
    summary = HistoryStore(tmp_path / "history.db").query_summary()

    assert summary.sample_count == 0
    assert summary.period_start is None
    assert summary.average_cpu_percent is None
    assert summary.peak_gpu_temperature_celsius is None
    assert summary.observed_network_sent_change_bytes is None


def test_counter_reset_is_not_reported_as_negative_transfer(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    start = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    store.record_sample(_snapshot(timestamp=start, sent=5_000, received=8_000))
    store.record_sample(
        _snapshot(timestamp=start + timedelta(minutes=1), sent=100, received=200)
    )

    summary = store.query_summary()

    assert summary.observed_network_sent_change_bytes is None
    assert summary.observed_network_received_change_bytes is None


def test_recent_samples_apply_time_filter_limit_and_gpu_counts(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    start = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    for offset in range(4):
        store.record_sample(
            _snapshot(
                timestamp=start + timedelta(hours=offset),
                cpu=offset,
                gpus=(_gpu(),) * offset,
            )
        )

    samples = store.recent_samples(since=start + timedelta(hours=1), limit=2)

    assert [sample.cpu_usage_percent for sample in samples] == [3, 2]
    assert [sample.gpu_count for sample in samples] == [3, 2]


def test_recent_alert_event_limit_returns_newest_first(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    start = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    for offset in range(3):
        timestamp = start + timedelta(minutes=offset)
        store.record_sample(
            _snapshot(timestamp=timestamp),
            (_event(timestamp, metric=f"metric.{offset}"),),
        )

    events = store.recent_alert_events(limit=2)

    assert [event.metric for event in events] == ["metric.2", "metric.1"]


def test_retention_cleanup_cascades_gpu_and_alert_rows(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    now = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    old = now - timedelta(days=31)
    store.record_sample(_snapshot(timestamp=old, gpus=(_gpu(),)), (_event(old),))
    store.record_sample(_snapshot(timestamp=now, gpus=(_gpu(),)), (_event(now),))

    deleted = store.cleanup(30, now=now)

    assert deleted == 1
    assert _rows(path, "SELECT COUNT(*) FROM snapshots")[0][0] == 1
    assert _rows(path, "SELECT COUNT(*) FROM gpu_samples")[0][0] == 1
    assert _rows(path, "SELECT COUNT(*) FROM alert_events")[0][0] == 1


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_query_limits_are_rejected(tmp_path, limit):
    store = HistoryStore(tmp_path / "history.db")

    with pytest.raises(HistoryError, match="positive integer"):
        store.recent_samples(limit=limit)


def test_naive_query_and_cleanup_timestamps_are_rejected(tmp_path):
    store = HistoryStore(tmp_path / "history.db")

    with pytest.raises(HistoryError, match="timezone-aware"):
        store.query_summary(since=datetime(2026, 8, 24))
    with pytest.raises(HistoryError, match="timezone-aware"):
        store.cleanup(30, now=datetime(2026, 8, 24))


def test_non_utc_snapshot_timestamp_is_persisted_as_utc(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    offset = timezone(timedelta(hours=4))

    store.record_sample(
        _snapshot(timestamp=datetime(2026, 8, 24, 12, 0, tzinfo=offset))
    )
    sample = store.recent_samples(limit=1)[0]

    assert sample.timestamp == datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    assert sample.timestamp.tzinfo is UTC


def test_invalid_parent_directory_produces_understandable_error(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file", encoding="utf-8")

    with pytest.raises(HistoryError, match="Could not create history directory"):
        HistoryStore(blocker / "history.db")


def test_unwritable_database_open_is_wrapped(monkeypatch, tmp_path):
    monkeypatch.setattr(
        history_module.sqlite3,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("attempt to write a readonly database")
        ),
    )

    with pytest.raises(HistoryError, match="open history database"):
        HistoryStore(tmp_path / "readonly.db")


def test_corrupt_database_produces_understandable_error(tmp_path):
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"not a sqlite database")

    with pytest.raises(HistoryError, match="initialize history database"):
        HistoryStore(path)
