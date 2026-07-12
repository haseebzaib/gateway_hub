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
