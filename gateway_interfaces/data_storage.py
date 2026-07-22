from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("/opt/metacrust/data/gateway_interfaces/gateway_interfaces.db")
DEFAULT_RETENTION_DAYS = 31


class GatewayInterfacesDataStorage:
    """Durable storage for data received from gateway_core sensor runtimes."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("METACRUST_INTERFACES_DB_PATH") or DEFAULT_DB_PATH)
        self.retention_days = max(1, int(os.environ.get("METACRUST_INTERFACES_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)))
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._last_maintenance_ms = 0

    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._migrate_locked()

    def close(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def _migrate_locked(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sensor_messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms        INTEGER NOT NULL,
                source_type  TEXT NOT NULL,
                source_id    TEXT NOT NULL,
                ok           INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                errors_json  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sensor_messages_source_time
                ON sensor_messages (source_type, source_id, ts_ms);

            CREATE TABLE IF NOT EXISTS sensor_readings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id  INTEGER NOT NULL REFERENCES sensor_messages(id) ON DELETE CASCADE,
                ts_ms       INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_id   TEXT NOT NULL,
                name        TEXT NOT NULL,
                value       REAL,
                unit        TEXT,
                address     INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_sensor_readings_series
                ON sensor_readings (source_type, source_id, name, ts_ms);

            CREATE TABLE IF NOT EXISTS rs232_sniffer_frames (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms       INTEGER NOT NULL,
                port        TEXT NOT NULL,
                device_path TEXT,
                size        INTEGER NOT NULL,
                ascii_text  TEXT,
                hex_text    TEXT NOT NULL,
                frame_json  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sniffer_port_time
                ON rs232_sniffer_frames (port, ts_ms);

            CREATE TABLE IF NOT EXISTS sensor_status_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms       INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_id   TEXT NOT NULL,
                status      TEXT NOT NULL,
                error       TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sensor_status_source_time
                ON sensor_status_events (source_type, source_id, ts_ms);

            CREATE TABLE IF NOT EXISTS sensor_sources (
                source_type TEXT NOT NULL,
                source_id   TEXT NOT NULL,
                first_seen_ms INTEGER NOT NULL,
                last_seen_ms  INTEGER NOT NULL,
                last_status TEXT NOT NULL,
                last_error  TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (source_type, source_id)
            );

            CREATE TABLE IF NOT EXISTS sensor_anomaly_events (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms          INTEGER NOT NULL,
                source_type    TEXT NOT NULL,
                source_id      TEXT NOT NULL,
                metric         TEXT,
                detector       TEXT,
                severity       TEXT,
                value          REAL,
                z_score        REAL,
                delta_value    REAL,
                slope_value    REAL,
                warning_limit  REAL,
                critical_limit REAL,
                min_value      REAL,
                max_value      REAL,
                alarm_name     TEXT,
                category       TEXT,
                metric_label   TEXT,
                headline       TEXT,
                message        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sensor_anomaly_source_time
                ON sensor_anomaly_events (source_type, source_id, ts_ms);
            """
        )
        self._conn.commit()

    def add_sensor_data(self, data: dict[str, Any]) -> int:
        ts_ms = _timestamp_ms(data)
        source_type, source_id = _source(data)
        samples = data.get("samples") if isinstance(data.get("samples"), list) else []
        errors = data.get("errors") if isinstance(data.get("errors"), list) else []
        payload = dict(data)
        payload.pop("errors", None)
        ok = bool(data.get("ok", True))
        with self._lock:
            self.open()
            assert self._conn is not None
            cursor = self._conn.execute(
                "INSERT INTO sensor_messages (ts_ms, source_type, source_id, ok, payload_json, errors_json) VALUES (?, ?, ?, ?, ?, ?)",
                (ts_ms, source_type, source_id, int(ok), _json(payload), _json(errors)),
            )
            message_id = int(cursor.lastrowid)
            rows = []
            for sample in samples:
                if not isinstance(sample, dict) or not str(sample.get("name") or ""):
                    continue
                rows.append((
                    message_id, ts_ms, source_type, source_id, str(sample["name"]),
                    _optional_float(sample.get("value")), str(sample.get("unit") or ""),
                    _optional_int(sample.get("address")),
                ))
            if rows:
                self._conn.executemany(
                    "INSERT INTO sensor_readings (message_id, ts_ms, source_type, source_id, name, value, unit, address) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            self._upsert_source_locked(source_type, source_id, ts_ms, "online" if ok else "error", _first_error(errors), 1)
            self._conn.commit()
            self._maybe_maintain_locked(ts_ms)
            return message_id

    def add_sniffer_frame(self, data: dict[str, Any]) -> int:
        ts_ms = _timestamp_ms(data)
        port = str(data.get("port") or "unknown")
        with self._lock:
            self.open()
            assert self._conn is not None
            cursor = self._conn.execute(
                """INSERT INTO rs232_sniffer_frames
                   (ts_ms, port, device_path, size, ascii_text, hex_text, frame_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts_ms, port, str(data.get("device_path") or ""), int(data.get("size") or 0),
                    str(data.get("ascii") or ""), str(data.get("hex") or ""), _json(data),
                ),
            )
            self._upsert_source_locked("rs232Sniffer", port, ts_ms, "online", None, 1)
            self._conn.commit()
            self._maybe_maintain_locked(ts_ms)
            return int(cursor.lastrowid)

    def add_status(self, data: dict[str, Any]) -> int:
        ts_ms = _timestamp_ms(data)
        source_type, source_id = _source(data)
        status = str(data.get("status") or "unknown")
        error = str(data.get("error") or "") or None
        with self._lock:
            self.open()
            assert self._conn is not None
            cursor = self._conn.execute(
                "INSERT INTO sensor_status_events (ts_ms, source_type, source_id, status, error) VALUES (?, ?, ?, ?, ?)",
                (ts_ms, source_type, source_id, status, error),
            )
            self._upsert_source_locked(source_type, source_id, ts_ms, status, error, 0)
            self._conn.commit()
            self._maybe_maintain_locked(ts_ms)
            return int(cursor.lastrowid)

    def sources(self) -> list[dict[str, Any]]:
        with self._lock:
            self.open()
            assert self._conn is not None
            return [dict(row) for row in self._conn.execute(
                "SELECT * FROM sensor_sources ORDER BY source_type, source_id"
            ).fetchall()]

    def readings(
        self, *, source_type: str | None = None, source_id: str | None = None,
        name: str | None = None, from_ms: int = 0, to_ms: int = 2**63 - 1, limit: int = 5000,
    ) -> list[dict[str, Any]]:
        clauses = ["ts_ms >= ?", "ts_ms <= ?"]
        values: list[Any] = [int(from_ms), int(to_ms)]
        for column, value in (("source_type", source_type), ("source_id", source_id), ("name", name)):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        values.append(max(1, min(int(limit), 50000)))
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                f"SELECT ts_ms, source_type, source_id, name, value, unit, address FROM sensor_readings WHERE {' AND '.join(clauses)} ORDER BY ts_ms DESC LIMIT ?",
                values,
            ).fetchall()
            return [dict(row) for row in reversed(rows)]

    def latest_readings(self, source_type: str, source_id: str) -> dict[str, dict[str, Any]]:
        """Most recent row per distinct metric name for one source."""
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                """SELECT sr.name, sr.ts_ms, sr.value, sr.unit, sr.address
                   FROM sensor_readings sr
                   JOIN (
                       SELECT name, MAX(ts_ms) AS max_ts
                       FROM sensor_readings
                       WHERE source_type = ? AND source_id = ?
                       GROUP BY name
                   ) latest ON latest.name = sr.name AND latest.max_ts = sr.ts_ms
                   WHERE sr.source_type = ? AND sr.source_id = ?""",
                (source_type, source_id, source_type, source_id),
            ).fetchall()
            return {row["name"]: dict(row) for row in rows}

    def distinct_reading_names(self, source_type: str, source_id: str) -> list[dict[str, str]]:
        """Metric names actually seen for a source, with their last-known unit —
        fallback for sources whose config doesn't declare registers up front (e.g. RS232)."""
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                """SELECT name, unit, MAX(ts_ms) AS ts_ms FROM sensor_readings
                   WHERE source_type = ? AND source_id = ? GROUP BY name ORDER BY name""",
                (source_type, source_id),
            ).fetchall()
            return [{"name": row["name"], "unit": row["unit"] or ""} for row in rows]

    def recent_values(self, source_type: str, source_id: str, name: str, limit: int = 20) -> list[float]:
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                """SELECT value FROM sensor_readings
                   WHERE source_type = ? AND source_id = ? AND name = ? AND value IS NOT NULL
                   ORDER BY ts_ms DESC LIMIT ?""",
                (source_type, source_id, name, max(1, min(int(limit), 500))),
            ).fetchall()
            return [row["value"] for row in reversed(rows)]

    def bucketed_readings(
        self, source_type: str, source_id: str, name: str, from_ms: int, to_ms: int, bucket_ms: int,
    ) -> list[dict[str, Any]]:
        """SQL-side time-bucketed aggregation — scales to long windows without
        pulling raw rows into Python."""
        bucket_ms = max(1000, int(bucket_ms))
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                """SELECT (ts_ms / ?) * ? AS bucket_ts, AVG(value) AS avg_v, MIN(value) AS min_v,
                          MAX(value) AS max_v, COUNT(*) AS n
                   FROM sensor_readings
                   WHERE source_type = ? AND source_id = ? AND name = ? AND ts_ms >= ? AND ts_ms <= ? AND value IS NOT NULL
                   GROUP BY bucket_ts ORDER BY bucket_ts""",
                (bucket_ms, bucket_ms, source_type, source_id, name, int(from_ms), int(to_ms)),
            ).fetchall()
            return [dict(row) for row in rows]

    def metric_stats(self, source_type: str, source_id: str, name: str, from_ms: int, to_ms: int) -> dict[str, Any]:
        with self._lock:
            self.open()
            assert self._conn is not None
            row = self._conn.execute(
                """SELECT COUNT(*) AS n, AVG(value) AS avg_v, MIN(value) AS min_v, MAX(value) AS max_v,
                          AVG(value * value) AS avg_sq
                   FROM sensor_readings
                   WHERE source_type = ? AND source_id = ? AND name = ? AND ts_ms >= ? AND ts_ms <= ? AND value IS NOT NULL""",
                (source_type, source_id, name, int(from_ms), int(to_ms)),
            ).fetchone()
            n = int(row["n"] or 0)
            if n == 0:
                return {"avg": None, "min": None, "max": None, "stddev": None, "sample_count": 0}
            avg_v = float(row["avg_v"])
            variance = max(0.0, float(row["avg_sq"]) - avg_v * avg_v)
            return {
                "avg": avg_v, "min": float(row["min_v"]), "max": float(row["max_v"]),
                "stddev": variance ** 0.5, "sample_count": n,
            }

    def status_events(
        self, *, source_type: str | None = None, source_id: str | None = None,
        from_ms: int = 0, to_ms: int = 2**63 - 1, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses = ["ts_ms >= ?", "ts_ms <= ?"]
        values: list[Any] = [int(from_ms), int(to_ms)]
        for column, value in (("source_type", source_type), ("source_id", source_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        values.append(max(1, min(int(limit), 10000)))
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                f"""SELECT ts_ms, source_type, source_id, status, error FROM sensor_status_events
                    WHERE {' AND '.join(clauses)} ORDER BY ts_ms DESC LIMIT ?""",
                values,
            ).fetchall()
            return [dict(row) for row in rows]

    def add_sensor_anomaly_events(self, events: list[dict[str, Any]]) -> None:
        """Persist a batch of normalized sensor anomaly events (see
        gateway_ipc.message_protocol.normalize_sensor_anomaly_message)."""
        if not events:
            return
        with self._lock:
            self.open()
            assert self._conn is not None
            self._conn.executemany(
                """
                INSERT INTO sensor_anomaly_events (
                    ts_ms, source_type, source_id, metric, detector, severity, value,
                    z_score, delta_value, slope_value,
                    warning_limit, critical_limit, min_value, max_value,
                    alarm_name, category, metric_label, headline, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        int(ev.get("timestamp_ms") or 0),
                        ev.get("source_type"),
                        ev.get("source_id"),
                        ev.get("metric"),
                        ev.get("detector"),
                        ev.get("severity"),
                        _optional_float(ev.get("value")),
                        _optional_float(ev.get("z_score")),
                        _optional_float(ev.get("delta_value")),
                        _optional_float(ev.get("slope_value")),
                        _optional_float(ev.get("warning_limit")),
                        _optional_float(ev.get("critical_limit")),
                        _optional_float(ev.get("min_value")),
                        _optional_float(ev.get("max_value")),
                        ev.get("alarm_name"),
                        ev.get("category"),
                        ev.get("metric_label"),
                        ev.get("headline"),
                        ev.get("message"),
                    )
                    for ev in events
                ],
            )
            self._conn.commit()
            self._maybe_maintain_locked(int(events[-1].get("timestamp_ms") or 0))

    def sensor_anomaly_events(
        self, *, source_type: str | None = None, source_id: str | None = None,
        from_ms: int = 0, to_ms: int = 2**63 - 1, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses = ["ts_ms >= ?", "ts_ms <= ?"]
        values: list[Any] = [int(from_ms), int(to_ms)]
        for column, value in (("source_type", source_type), ("source_id", source_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        values.append(max(1, min(int(limit), 10000)))
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                f"""SELECT ts_ms, source_type, source_id, metric, detector, severity, value,
                           z_score, delta_value, slope_value, warning_limit, critical_limit,
                           min_value, max_value, alarm_name, category, metric_label, headline, message
                    FROM sensor_anomaly_events WHERE {' AND '.join(clauses)} ORDER BY ts_ms DESC LIMIT ?""",
                values,
            ).fetchall()
            return [dict(row) for row in rows]

    def grouped_sensor_anomalies(self, source_type: str, source_id: str, since_ms: int) -> list[dict[str, Any]]:
        """Collapse repeats into one row per (metric, category, severity) for
        this sensor — mirrors monitor_storage.MonitorStorage.grouped_anomalies()."""
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                """
                SELECT metric, metric_label, category, severity,
                       COUNT(*)     AS count,
                       MIN(ts_ms)   AS first_ts,
                       MAX(ts_ms)   AS latest_ts,
                       MIN(value)   AS min_value,
                       MAX(value)   AS max_value,
                       (SELECT value FROM sensor_anomaly_events e2
                          WHERE e2.source_type = e1.source_type AND e2.source_id = e1.source_id
                            AND e2.metric IS e1.metric AND e2.category IS e1.category AND e2.severity IS e1.severity
                            AND e2.ts_ms >= ?
                          ORDER BY e2.ts_ms DESC LIMIT 1) AS latest_value,
                       (SELECT headline FROM sensor_anomaly_events e3
                          WHERE e3.source_type = e1.source_type AND e3.source_id = e1.source_id
                            AND e3.metric IS e1.metric AND e3.category IS e1.category AND e3.severity IS e1.severity
                            AND e3.ts_ms >= ?
                          ORDER BY e3.ts_ms DESC LIMIT 1) AS latest_headline,
                       (SELECT message FROM sensor_anomaly_events e4
                          WHERE e4.source_type = e1.source_type AND e4.source_id = e1.source_id
                            AND e4.metric IS e1.metric AND e4.category IS e1.category AND e4.severity IS e1.severity
                            AND e4.ts_ms >= ?
                          ORDER BY e4.ts_ms DESC LIMIT 1) AS latest_message
                FROM sensor_anomaly_events e1
                WHERE source_type = ? AND source_id = ? AND ts_ms >= ?
                GROUP BY metric, category, severity
                ORDER BY latest_ts DESC
                """,
                (int(since_ms), int(since_ms), int(since_ms), source_type, source_id, int(since_ms)),
            ).fetchall()
            return [dict(row) for row in rows]

    def sensor_messages(
        self, *, source_type: str | None = None, source_id: str | None = None,
        from_ms: int = 0, to_ms: int = 2**63 - 1, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses = ["ts_ms >= ?", "ts_ms <= ?"]
        values: list[Any] = [int(from_ms), int(to_ms)]
        for column, value in (("source_type", source_type), ("source_id", source_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        values.append(max(1, min(int(limit), 10000)))
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                f"SELECT id, ts_ms, source_type, source_id, ok, payload_json, errors_json FROM sensor_messages WHERE {' AND '.join(clauses)} ORDER BY ts_ms DESC LIMIT ?",
                values,
            ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            item["ok"] = bool(item["ok"])
            item["payload"] = json.loads(item.pop("payload_json"))
            item["errors"] = json.loads(item.pop("errors_json"))
            result.append(item)
        return result

    def sniffer_frames(
        self, *, port: str | None = None, from_ms: int = 0,
        to_ms: int = 2**63 - 1, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses = ["ts_ms >= ?", "ts_ms <= ?"]
        values: list[Any] = [int(from_ms), int(to_ms)]
        if port is not None:
            clauses.append("port = ?")
            values.append(port)
        values.append(max(1, min(int(limit), 10000)))
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                f"SELECT ts_ms, port, device_path, size, ascii_text AS ascii, hex_text AS hex FROM rs232_sniffer_frames WHERE {' AND '.join(clauses)} ORDER BY ts_ms DESC LIMIT ?",
                values,
            ).fetchall()
            return [dict(row) for row in reversed(rows)]

    def _upsert_source_locked(
        self, source_type: str, source_id: str, ts_ms: int,
        status: str, error: str | None, message_increment: int,
    ) -> None:
        assert self._conn is not None
        self._conn.execute(
            """INSERT INTO sensor_sources
               (source_type, source_id, first_seen_ms, last_seen_ms, last_status, last_error, message_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_type, source_id) DO UPDATE SET
                 last_seen_ms = excluded.last_seen_ms,
                 last_status = excluded.last_status,
                 last_error = excluded.last_error,
                 message_count = sensor_sources.message_count + excluded.message_count""",
            (source_type, source_id, ts_ms, ts_ms, status, error, message_increment),
        )

    def _maybe_maintain_locked(self, now_ms: int) -> None:
        if now_ms - self._last_maintenance_ms < 600_000:
            return
        self._last_maintenance_ms = now_ms
        assert self._conn is not None
        cutoff = now_ms - self.retention_days * 86_400_000
        self._conn.execute("DELETE FROM sensor_messages WHERE ts_ms < ?", (cutoff,))
        self._conn.execute("DELETE FROM rs232_sniffer_frames WHERE ts_ms < ?", (cutoff,))
        self._conn.execute("DELETE FROM sensor_status_events WHERE ts_ms < ?", (cutoff,))
        self._conn.execute("DELETE FROM sensor_anomaly_events WHERE ts_ms < ?", (cutoff,))
        self._conn.commit()


def _timestamp_ms(data: dict[str, Any]) -> int:
    try:
        value = int(data.get("timestamp_ms") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else int(time.time() * 1000)


def _source(data: dict[str, Any]) -> tuple[str, str]:
    return str(data.get("source_type") or "unknown"), str(data.get("source_id") or "unknown")


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_error(errors: list[Any]) -> str | None:
    for error in errors:
        if isinstance(error, dict) and error.get("error"):
            return str(error["error"])
    return None
