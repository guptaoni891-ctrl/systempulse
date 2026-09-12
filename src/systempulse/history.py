from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from systempulse.energy import EnergyIntegration, PowerEnergyAccumulator
from systempulse.models import (
    AlertEvent,
    AlertSeverity,
    AlertTransition,
    HistoricalSample,
    HistorySummary,
    PowerHistorySummary,
    SystemSnapshot,
)

SCHEMA_VERSION = 2

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE snapshots (
        id INTEGER PRIMARY KEY,
        timestamp_utc TEXT NOT NULL,
        cpu_usage_percent REAL NOT NULL,
        ram_usage_percent REAL NOT NULL,
        ram_used_bytes INTEGER NOT NULL,
        ram_total_bytes INTEGER NOT NULL,
        disk_usage_percent REAL NOT NULL,
        disk_used_bytes INTEGER NOT NULL,
        disk_total_bytes INTEGER NOT NULL,
        cpu_temperature_celsius REAL,
        network_bytes_sent INTEGER NOT NULL,
        network_bytes_received INTEGER NOT NULL,
        upload_bytes_per_second REAL NOT NULL,
        download_bytes_per_second REAL NOT NULL
    )
    """,
    """
    CREATE TABLE gpu_samples (
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
        gpu_index INTEGER NOT NULL,
        name TEXT NOT NULL,
        usage_percent REAL NOT NULL,
        temperature_celsius REAL NOT NULL,
        vram_used_mib REAL NOT NULL,
        vram_total_mib REAL NOT NULL,
        power_watts REAL,
        PRIMARY KEY (snapshot_id, gpu_index)
    )
    """,
    """
    CREATE TABLE alert_events (
        id INTEGER PRIMARY KEY,
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
        timestamp_utc TEXT NOT NULL,
        metric TEXT NOT NULL,
        label TEXT NOT NULL,
        severity TEXT NOT NULL,
        transition TEXT NOT NULL,
        current_value REAL NOT NULL,
        threshold REAL NOT NULL,
        unit TEXT NOT NULL,
        message TEXT NOT NULL
    )
    """,
    "CREATE INDEX snapshots_timestamp_idx ON snapshots(timestamp_utc)",
    "CREATE INDEX alert_events_timestamp_idx ON alert_events(timestamp_utc)",
    "CREATE INDEX alert_events_metric_idx ON alert_events(metric)",
)

_REQUIRED_TABLES = {"snapshots", "gpu_samples", "alert_events"}
_VERSION_2_SNAPSHOT_COLUMNS = {
    "cpu_package_watts",
    "gpu_total_watts",
    "cpu_gpu_watts",
    "estimated_system_watts",
    "estimated_wall_watts",
    "actual_wall_watts",
    "cpu_power_source",
}
_VERSION_2_MIGRATION_STATEMENTS = tuple(
    f"ALTER TABLE snapshots ADD COLUMN {column} {column_type}"
    for column, column_type in (
        ("cpu_package_watts", "REAL"),
        ("gpu_total_watts", "REAL"),
        ("cpu_gpu_watts", "REAL"),
        ("estimated_system_watts", "REAL"),
        ("estimated_wall_watts", "REAL"),
        ("actual_wall_watts", "REAL"),
        ("cpu_power_source", "TEXT"),
    )
)
_POWER_METRIC_COLUMNS = (
    "cpu_package_watts",
    "gpu_total_watts",
    "cpu_gpu_watts",
    "estimated_system_watts",
    "estimated_wall_watts",
    "actual_wall_watts",
)


class HistoryError(RuntimeError):
    """Raised when local history cannot be initialized, written, or queried."""


class UnsupportedSchemaVersionError(HistoryError):
    """Raised when a database was created by a newer unsupported SystemPulse."""


class HistoryStore:
    """Persist authoritative snapshots and alert transitions in local SQLite."""

    def __init__(self, database: str | Path) -> None:
        self.path = Path(database).expanduser().resolve(strict=False)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise HistoryError(
                f"Could not create history directory {self.path.parent}: {error}"
            ) from error
        self._initialize()

    def schema_version(self) -> int:
        try:
            with closing(self._connect()) as connection:
                return int(connection.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.Error as error:
            raise self._database_error("read schema version", error) from error

    def record_sample(
        self,
        snapshot: SystemSnapshot,
        alert_events: Iterable[AlertEvent] = (),
    ) -> int:
        events = tuple(alert_events)
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    """
                    INSERT INTO snapshots (
                        timestamp_utc,
                        cpu_usage_percent,
                        ram_usage_percent,
                        ram_used_bytes,
                        ram_total_bytes,
                        disk_usage_percent,
                        disk_used_bytes,
                        disk_total_bytes,
                        cpu_temperature_celsius,
                        network_bytes_sent,
                        network_bytes_received,
                        upload_bytes_per_second,
                        download_bytes_per_second,
                        cpu_package_watts,
                        gpu_total_watts,
                        cpu_gpu_watts,
                        estimated_system_watts,
                        estimated_wall_watts,
                        actual_wall_watts,
                        cpu_power_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _timestamp_text(snapshot.timestamp),
                        snapshot.cpu_usage_percent,
                        snapshot.ram_usage_percent,
                        snapshot.ram_used_bytes,
                        snapshot.ram_total_bytes,
                        snapshot.disk_usage_percent,
                        snapshot.disk_used_bytes,
                        snapshot.disk_total_bytes,
                        snapshot.cpu_temperature_celsius,
                        snapshot.network.bytes_sent,
                        snapshot.network.bytes_received,
                        snapshot.network_speed.upload_bytes_per_second,
                        snapshot.network_speed.download_bytes_per_second,
                        snapshot.power.cpu_package_watts,
                        snapshot.power.gpu_total_watts,
                        snapshot.power.cpu_gpu_watts,
                        snapshot.power.estimated_system_watts,
                        snapshot.power.estimated_wall_watts,
                        snapshot.power.actual_wall_watts,
                        snapshot.power.cpu_source,
                    ),
                )
                snapshot_id = cursor.lastrowid
                if snapshot_id is None:
                    raise HistoryError(
                        f"History database {self.path} did not return a snapshot identifier."
                    )
                connection.executemany(
                    """
                    INSERT INTO gpu_samples (
                        snapshot_id,
                        gpu_index,
                        name,
                        usage_percent,
                        temperature_celsius,
                        vram_used_mib,
                        vram_total_mib,
                        power_watts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            snapshot_id,
                            index,
                            gpu.name,
                            gpu.usage_percent,
                            gpu.temperature_celsius,
                            gpu.vram_used_mib,
                            gpu.vram_total_mib,
                            gpu.power_watts,
                        )
                        for index, gpu in enumerate(snapshot.gpus)
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO alert_events (
                        snapshot_id,
                        timestamp_utc,
                        metric,
                        label,
                        severity,
                        transition,
                        current_value,
                        threshold,
                        unit,
                        message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            snapshot_id,
                            _timestamp_text(event.timestamp),
                            event.metric,
                            event.label,
                            event.severity.value,
                            event.transition.value,
                            event.current_value,
                            event.threshold,
                            event.unit,
                            event.message,
                        )
                        for event in events
                    ),
                )
                return snapshot_id
        except sqlite3.Error as error:
            raise self._database_error("record a history sample", error) from error

    def query_summary(self, *, since: datetime | None = None) -> HistorySummary:
        clause, parameters = _since_clause(since)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"""
                    SELECT
                        MIN(timestamp_utc) AS period_start,
                        MAX(timestamp_utc) AS period_end,
                        COUNT(*) AS sample_count,
                        AVG(cpu_usage_percent) AS average_cpu,
                        MAX(cpu_usage_percent) AS peak_cpu,
                        AVG(ram_usage_percent) AS average_memory,
                        MAX(ram_usage_percent) AS peak_memory,
                        AVG(disk_usage_percent) AS average_disk,
                        MAX(disk_usage_percent) AS peak_disk,
                        MAX(cpu_temperature_celsius) AS peak_cpu_temperature
                    FROM snapshots
                    {clause}
                    """,
                    parameters,
                ).fetchone()
                gpu_row = connection.execute(
                    f"""
                    SELECT MAX(gpu.temperature_celsius) AS peak_gpu_temperature
                    FROM gpu_samples AS gpu
                    JOIN snapshots AS sample ON sample.id = gpu.snapshot_id
                    {clause.replace("timestamp_utc", "sample.timestamp_utc")}
                    """,
                    parameters,
                ).fetchone()
                alert_row = connection.execute(
                    f"""
                    SELECT COUNT(*) AS event_count
                    FROM alert_events AS event
                    JOIN snapshots AS sample ON sample.id = event.snapshot_id
                    {clause.replace("timestamp_utc", "sample.timestamp_utc")}
                    """,
                    parameters,
                ).fetchone()
                network_change = self._network_change(connection, clause, parameters)
                power_summary = _power_history_summary(
                    connection.execute(
                        f"""
                        SELECT
                            timestamp_utc,
                            cpu_package_watts,
                            gpu_total_watts,
                            cpu_gpu_watts,
                            estimated_system_watts,
                            estimated_wall_watts,
                            actual_wall_watts
                        FROM snapshots
                        {clause}
                        ORDER BY timestamp_utc ASC, id ASC
                        """,
                        parameters,
                    )
                )
        except sqlite3.Error as error:
            raise self._database_error("query history summary", error) from error

        count = int(row["sample_count"])
        return HistorySummary(
            period_start=_parse_timestamp(row["period_start"]),
            period_end=_parse_timestamp(row["period_end"]),
            sample_count=count,
            average_cpu_percent=_optional_float(row["average_cpu"]),
            peak_cpu_percent=_optional_float(row["peak_cpu"]),
            average_memory_percent=_optional_float(row["average_memory"]),
            peak_memory_percent=_optional_float(row["peak_memory"]),
            average_disk_percent=_optional_float(row["average_disk"]),
            peak_disk_percent=_optional_float(row["peak_disk"]),
            peak_cpu_temperature_celsius=_optional_float(row["peak_cpu_temperature"]),
            peak_gpu_temperature_celsius=_optional_float(gpu_row["peak_gpu_temperature"]),
            observed_network_sent_change_bytes=network_change[0],
            observed_network_received_change_bytes=network_change[1],
            alert_event_count=int(alert_row["event_count"]),
            power=power_summary,
        )

    def recent_samples(
        self,
        *,
        since: datetime | None = None,
        limit: int = 20,
    ) -> tuple[HistoricalSample, ...]:
        _validate_limit(limit)
        clause, parameters = _since_clause(since)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"""
                    SELECT
                        sample.timestamp_utc,
                        sample.cpu_usage_percent,
                        sample.ram_usage_percent,
                        sample.disk_usage_percent,
                        sample.cpu_temperature_celsius,
                        sample.upload_bytes_per_second,
                        sample.download_bytes_per_second,
                        sample.cpu_package_watts,
                        sample.gpu_total_watts,
                        sample.cpu_gpu_watts,
                        sample.estimated_system_watts,
                        sample.estimated_wall_watts,
                        sample.actual_wall_watts,
                        sample.cpu_power_source,
                        COUNT(gpu.gpu_index) AS gpu_count
                    FROM snapshots AS sample
                    LEFT JOIN gpu_samples AS gpu ON gpu.snapshot_id = sample.id
                    {clause.replace("timestamp_utc", "sample.timestamp_utc")}
                    GROUP BY sample.id
                    ORDER BY sample.timestamp_utc DESC, sample.id DESC
                    LIMIT ?
                    """,
                    (*parameters, limit),
                ).fetchall()
        except sqlite3.Error as error:
            raise self._database_error("query recent history samples", error) from error

        return tuple(
            HistoricalSample(
                timestamp=_required_timestamp(row["timestamp_utc"]),
                cpu_usage_percent=float(row["cpu_usage_percent"]),
                memory_usage_percent=float(row["ram_usage_percent"]),
                disk_usage_percent=float(row["disk_usage_percent"]),
                cpu_temperature_celsius=_optional_float(row["cpu_temperature_celsius"]),
                upload_bytes_per_second=float(row["upload_bytes_per_second"]),
                download_bytes_per_second=float(row["download_bytes_per_second"]),
                gpu_count=int(row["gpu_count"]),
                cpu_package_watts=_optional_float(row["cpu_package_watts"]),
                gpu_total_watts=_optional_float(row["gpu_total_watts"]),
                cpu_gpu_watts=_optional_float(row["cpu_gpu_watts"]),
                estimated_system_watts=_optional_float(row["estimated_system_watts"]),
                estimated_wall_watts=_optional_float(row["estimated_wall_watts"]),
                actual_wall_watts=_optional_float(row["actual_wall_watts"]),
                cpu_power_source=row["cpu_power_source"],
            )
            for row in rows
        )

    def recent_alert_events(self, *, limit: int = 20) -> tuple[AlertEvent, ...]:
        _validate_limit(limit)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        timestamp_utc,
                        metric,
                        label,
                        severity,
                        transition,
                        current_value,
                        threshold,
                        unit,
                        message
                    FROM alert_events
                    ORDER BY timestamp_utc DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as error:
            raise self._database_error("query alert-event history", error) from error

        try:
            return tuple(
                AlertEvent(
                    timestamp=_required_timestamp(row["timestamp_utc"]),
                    metric=row["metric"],
                    label=row["label"],
                    severity=AlertSeverity(row["severity"]),
                    transition=AlertTransition(row["transition"]),
                    current_value=float(row["current_value"]),
                    threshold=float(row["threshold"]),
                    unit=row["unit"],
                    message=row["message"],
                )
                for row in rows
            )
        except (TypeError, ValueError) as error:
            raise HistoryError(
                f"History database {self.path} contains invalid alert-event data: {error}"
            ) from error

    def cleanup(self, retention_days: int, *, now: datetime | None = None) -> int:
        if isinstance(retention_days, bool) or not isinstance(retention_days, int):
            raise HistoryError("History retention days must be an integer.")
        if retention_days <= 0:
            raise HistoryError("History retention days must be greater than zero.")
        reference = datetime.now(UTC) if now is None else _as_utc(now)
        cutoff = reference - timedelta(days=retention_days)
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    "DELETE FROM snapshots WHERE timestamp_utc < ?",
                    (_timestamp_text(cutoff),),
                )
                return int(cursor.rowcount)
        except sqlite3.Error as error:
            raise self._database_error("clean up expired history", error) from error

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version > SCHEMA_VERSION:
                    raise UnsupportedSchemaVersionError(
                        f"History database {self.path} uses schema version {version}; "
                        f"this SystemPulse supports up to version {SCHEMA_VERSION}."
                    )
                if version == 0:
                    self._migrate_to_version_1(connection)
                    version = 1
                if version == 1:
                    self._migrate_to_version_2(connection)
                self._validate_schema(connection)
        except UnsupportedSchemaVersionError:
            raise
        except sqlite3.Error as error:
            raise self._database_error("initialize history database", error) from error

    def _migrate_to_version_1(self, connection: sqlite3.Connection) -> None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise

    def _migrate_to_version_2(self, connection: sqlite3.Connection) -> None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in _VERSION_2_MIGRATION_STATEMENTS:
                connection.execute(statement)
            connection.execute("PRAGMA user_version = 2")
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ?",
            ("table",),
        ).fetchall()
        tables = {row["name"] for row in rows}
        missing = sorted(_REQUIRED_TABLES - tables)
        if missing:
            names = ", ".join(missing)
            raise HistoryError(
                f"History database {self.path} has an incomplete version 2 schema; "
                f"missing table(s): {names}."
            )
        snapshot_rows = connection.execute("PRAGMA table_info(snapshots)").fetchall()
        snapshot_columns = {row["name"] for row in snapshot_rows}
        missing_columns = sorted(_VERSION_2_SNAPSHOT_COLUMNS - snapshot_columns)
        if missing_columns:
            names = ", ".join(missing_columns)
            raise HistoryError(
                f"History database {self.path} has an incomplete version 2 schema; "
                f"snapshots is missing column(s): {names}."
            )

    def _connect(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            return connection
        except (OSError, sqlite3.Error) as error:
            if connection is not None:
                connection.close()
            raise self._database_error("open history database", error) from error

    def _network_change(
        self,
        connection: sqlite3.Connection,
        clause: str,
        parameters: tuple[str, ...],
    ) -> tuple[int | None, int | None]:
        if not connection.execute(
            f"SELECT 1 FROM snapshots {clause} LIMIT 1", parameters
        ).fetchone():
            return None, None
        first = connection.execute(
            f"""
            SELECT id, network_bytes_sent, network_bytes_received
            FROM snapshots
            {clause}
            ORDER BY timestamp_utc ASC, id ASC
            LIMIT 1
            """,
            parameters,
        ).fetchone()
        last = connection.execute(
            f"""
            SELECT id, network_bytes_sent, network_bytes_received
            FROM snapshots
            {clause}
            ORDER BY timestamp_utc DESC, id DESC
            LIMIT 1
            """,
            parameters,
        ).fetchone()
        if first["id"] == last["id"]:
            return None, None
        return (
            _counter_change(first["network_bytes_sent"], last["network_bytes_sent"]),
            _counter_change(first["network_bytes_received"], last["network_bytes_received"]),
        )

    def _database_error(self, action: str, error: BaseException) -> HistoryError:
        return HistoryError(f"Could not {action} using {self.path}: {error}")


def _since_clause(since: datetime | None) -> tuple[str, tuple[str, ...]]:
    if since is None:
        return "", ()
    return "WHERE timestamp_utc >= ?", (_timestamp_text(since),)


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise HistoryError("History query limit must be a positive integer.")


def _timestamp_text(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoryError("History timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except (TypeError, ValueError) as error:
        raise HistoryError(f"History database contains an invalid timestamp: {value!r}.") from error


def _required_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise HistoryError(f"History database contains an invalid timestamp: {value!r}.")
    timestamp = _parse_timestamp(value)
    if timestamp is None:  # Defensive narrowing; a string cannot parse as None.
        raise HistoryError(f"History database contains an invalid timestamp: {value!r}.")
    return timestamp


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (str, bytes, int, float)):
        raise HistoryError(f"History database contains an invalid number: {value!r}.")
    return float(value)


def _power_history_summary(rows: Iterable[sqlite3.Row]) -> PowerHistorySummary:
    accumulators = {column: PowerEnergyAccumulator() for column in _POWER_METRIC_COLUMNS}
    peaks: dict[str, float | None] = dict.fromkeys(_POWER_METRIC_COLUMNS)
    origin: datetime | None = None

    for row in rows:
        timestamp = _required_timestamp(row["timestamp_utc"])
        if origin is None:
            origin = timestamp
        elapsed_seconds = (timestamp - origin).total_seconds()
        for column in _POWER_METRIC_COLUMNS:
            watts = _optional_float(row[column])
            accumulators[column].observe(elapsed_seconds, watts)
            if watts is not None and math.isfinite(watts) and watts >= 0.0:
                peak = peaks[column]
                if peak is None or watts > peak:
                    peaks[column] = watts

    integrations = {column: accumulator.result for column, accumulator in accumulators.items()}
    estimated_wall = integrations["estimated_wall_watts"]
    actual_wall = integrations["actual_wall_watts"]
    return PowerHistorySummary(
        average_cpu_package_watts=_time_weighted_average(integrations["cpu_package_watts"]),
        peak_cpu_package_watts=peaks["cpu_package_watts"],
        average_gpu_total_watts=_time_weighted_average(integrations["gpu_total_watts"]),
        peak_gpu_total_watts=peaks["gpu_total_watts"],
        average_cpu_gpu_watts=_time_weighted_average(integrations["cpu_gpu_watts"]),
        peak_cpu_gpu_watts=peaks["cpu_gpu_watts"],
        average_estimated_system_watts=_time_weighted_average(
            integrations["estimated_system_watts"]
        ),
        peak_estimated_system_watts=peaks["estimated_system_watts"],
        average_estimated_wall_watts=_time_weighted_average(estimated_wall),
        peak_estimated_wall_watts=peaks["estimated_wall_watts"],
        average_actual_wall_watts=_time_weighted_average(actual_wall),
        peak_actual_wall_watts=peaks["actual_wall_watts"],
        estimated_wall_energy_wh=estimated_wall.energy_wh,
        actual_wall_energy_wh=actual_wall.energy_wh,
        estimated_wall_observed_duration_seconds=estimated_wall.observed_duration_seconds,
        actual_wall_observed_duration_seconds=actual_wall.observed_duration_seconds,
    )


def _time_weighted_average(integration: EnergyIntegration) -> float | None:
    if integration.observed_duration_seconds <= 0.0:
        return None
    return integration.energy_wh * 3600.0 / integration.observed_duration_seconds


def _counter_change(first: int, last: int) -> int | None:
    change = int(last) - int(first)
    return change if change >= 0 else None
