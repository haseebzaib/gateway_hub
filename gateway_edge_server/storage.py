from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("edge_server")

DEFAULT_DB_PATH = Path("/opt/metacrust/data/edge_server/edge_server.db")


try:
    from sqlcipher3 import dbapi2 as sqlcipher  # type: ignore
except Exception:  # pragma: no cover - depends on target image packages
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher  # type: ignore
    except Exception:  # pragma: no cover - depends on target image packages
        sqlcipher = None


class EdgeServerStorage:
    def __init__(self, db_path: Path | None = None, db_key: str | None = None) -> None:
        self.db_path = Path(
            db_path
            or os.environ.get("METACRUST_EDGE_DB_PATH")
            or DEFAULT_DB_PATH
        )
        self.db_key = db_key or os.environ.get("METACRUST_EDGE_DB_KEY") or os.environ.get("METACRUST_DB_KEY") or ""
        self._lock = threading.RLock()
        self._conn: Any | None = None

    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            if sqlcipher is None:
                raise RuntimeError("SQLCipher Python binding missing. Install sqlcipher3.")
            if not self.db_key:
                raise RuntimeError("SQLCipher DB key missing. Set METACRUST_EDGE_DB_KEY or METACRUST_DB_KEY.")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlcipher.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlcipher.Row
            self._conn.execute(f"PRAGMA key = {_sql_quote(self.db_key)}")
            self._conn.execute("PRAGMA cipher_memory_security = ON")
            LOGGER.info("storage_open encrypted=true path=%s", self.db_path)
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._migrate_locked()

    def close(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            self._conn.close()
            self._conn = None

    def save_message(self, record: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
        self.open()
        payload_json = record.get("payload_json")
        if payload_json is not None and not isinstance(payload_json, str):
            payload_json = json.dumps(payload_json, separators=(",", ":"), ensure_ascii=False)
        details_json = record.get("details_json")
        if details_json is not None and not isinstance(details_json, str):
            details_json = json.dumps(details_json, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO messages (
                    received_at, protocol, device_id, identity_source, source_ip, route,
                    endpoint_name, payload_type, payload_size, payload_hash, payload_json,
                    payload_raw, device_timestamp, sequence, accepted, reject_reason, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.get("received_at"),
                    record.get("protocol"),
                    record.get("device_id"),
                    record.get("identity_source"),
                    record.get("source_ip"),
                    record.get("route"),
                    record.get("endpoint_name"),
                    record.get("payload_type"),
                    int(record.get("payload_size") or 0),
                    record.get("payload_hash"),
                    payload_json,
                    record.get("payload_raw"),
                    record.get("device_timestamp"),
                    record.get("sequence"),
                    1 if record.get("accepted", True) else 0,
                    record.get("reject_reason"),
                    details_json,
                ),
            )
            message_id = int(cur.lastrowid)
            events = self._update_device_state_locked(record)
            for event in events:
                self._insert_event_locked(event)
            self._conn.commit()
            return message_id, events

    def update_device_state(self, record: dict[str, Any]) -> None:
        self.open()
        with self._lock:
            events = self._update_device_state_locked(record)
            for event in events:
                self._insert_event_locked(event)
            self._conn.commit()

    def _update_device_state_locked(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        device_id = str(record.get("device_id") or "unknown")
        protocol = str(record.get("protocol") or "unknown")
        received_at = str(record.get("received_at") or "")
        source_ip = str(record.get("source_ip") or "")
        route = str(record.get("route") or "")
        sequence = record.get("sequence")
        payload_size = int(record.get("payload_size") or 0)
        existing = self._conn.execute(
            "SELECT * FROM device_state WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        events = _anomaly_events(record, dict(existing) if existing else None)
        received_dt = _parse_time(received_at)
        last_seen_dt = _parse_time(existing["last_seen_at"]) if existing else None
        interval_ms = _interval_ms(last_seen_dt, received_dt)
        avg_interval_ms = _rolling_avg(existing["avg_interval_ms"] if existing else None, interval_ms)
        avg_payload_size = _rolling_avg(existing["avg_payload_size"] if existing else None, payload_size)
        online = 1 if protocol in {"MQTT", "MQTTS"} else 0
        if existing is None:
            self._conn.execute(
                """
                INSERT INTO device_state (
                    device_id, protocol, first_seen_at, last_seen_at, last_source_ip,
                    last_route, last_sequence, message_count, avg_interval_ms,
                    last_interval_ms, last_payload_size, avg_payload_size, last_payload_hash,
                    online, last_connected_at, anomaly_count, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'recent')
                """,
                (
                    device_id,
                    protocol,
                    received_at,
                    received_at,
                    source_ip,
                    route,
                    sequence,
                    avg_interval_ms,
                    interval_ms,
                    payload_size,
                    avg_payload_size,
                    record.get("payload_hash"),
                    online,
                    received_at if online else None,
                    len(events),
                ),
            )
        else:
            self._conn.execute(
                """
                UPDATE device_state
                SET protocol = ?, last_seen_at = ?, last_source_ip = ?, last_route = ?,
                    last_sequence = ?, message_count = message_count + 1,
                    avg_interval_ms = ?, last_interval_ms = ?, last_payload_size = ?,
                    avg_payload_size = ?, last_payload_hash = ?, online = ?,
                    last_connected_at = CASE WHEN ? = 1 AND online = 0 THEN ? ELSE last_connected_at END,
                    anomaly_count = anomaly_count + ?, status = 'recent'
                WHERE device_id = ?
                """,
                (
                    protocol,
                    received_at,
                    source_ip,
                    route,
                    sequence,
                    avg_interval_ms,
                    interval_ms,
                    payload_size,
                    avg_payload_size,
                    record.get("payload_hash"),
                    online,
                    online,
                    received_at,
                    len(events),
                    device_id,
                ),
            )
        return events

    def mark_mqtt_disconnected(
        self,
        client_id: str,
        protocol: str,
        source_ip: str,
        clean: bool,
        device_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        disconnected_at = _utc_now()
        targets = sorted({client_id, *(device_ids or [])})
        event = {
            "timestamp": disconnected_at,
            "severity": "info" if clean else "warning",
            "type": "mqtt_disconnected",
            "protocol": protocol,
            "device_id": client_id,
            "route": "",
            "source": client_id,
            "message": f"MQTT client {'cleanly disconnected' if clean else 'disconnected'}: {client_id}",
            "details": {"source_ip": source_ip, "clean": clean, "device_ids": targets},
        }
        self.open()
        with self._lock:
            if targets:
                placeholders = ",".join("?" for _ in targets)
                self._conn.execute(
                    f"""
                    UPDATE device_state
                    SET online = 0, last_disconnected_at = ?, status = 'disconnected'
                    WHERE device_id IN ({placeholders})
                    """,
                    (disconnected_at, *targets),
                )
            self._insert_event_locked(event)
            self._conn.commit()
        return event

    def save_event(self, event: dict[str, Any]) -> int:
        self.open()
        with self._lock:
            rowid = self._insert_event_locked(event)
            self._conn.commit()
            return rowid

    def _insert_event_locked(self, event: dict[str, Any]) -> int:
        details = event.get("details_json") or event.get("details") or {}
        if not isinstance(details, str):
            details = json.dumps(details, separators=(",", ":"), ensure_ascii=False)
        cur = self._conn.execute(
            """
            INSERT INTO events (
                created_at, severity, event_type, protocol, device_id, route, source, message, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("created_at") or event.get("timestamp"),
                event.get("severity") or "info",
                event.get("event_type") or event.get("type"),
                event.get("protocol"),
                event.get("device_id"),
                event.get("route"),
                event.get("source"),
                event.get("message"),
                details,
            ),
        )
        return int(cur.lastrowid)

    def message_count(self) -> int:
        self.open()
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS count FROM messages").fetchone()
            return int(row["count"] if row else 0)

    def recent_devices(self, limit: int = 30) -> list[dict[str, Any]]:
        self.open()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT device_id, protocol, last_route AS endpoint, last_source_ip AS peer,
                       last_seen_at AS last_seen, message_count, status, last_interval_ms,
                       avg_interval_ms, last_payload_size, avg_payload_size, anomaly_count,
                       online
                FROM device_state
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_device_health(dict(row)) for row in rows]

    def protocol_metrics(self, protocol_group: str) -> dict[str, Any]:
        self.open()
        protocols = ("HTTP", "HTTPS") if protocol_group == "http" else ("MQTT", "MQTTS")
        placeholders = ",".join("?" for _ in protocols)
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) AS count FROM messages WHERE protocol IN ({placeholders})",
                protocols,
            ).fetchone()["count"]
            device_count = self._conn.execute(
                f"SELECT COUNT(DISTINCT device_id) AS count FROM messages WHERE protocol IN ({placeholders})",
                protocols,
            ).fetchone()["count"]
            payload = self._conn.execute(
                f"""
                SELECT AVG(payload_size) AS avg_size, MAX(payload_size) AS max_size
                FROM messages WHERE protocol IN ({placeholders})
                """,
                protocols,
            ).fetchone()
            routes = self._conn.execute(
                f"""
                SELECT route, COUNT(*) AS count, COUNT(DISTINCT device_id) AS devices,
                       MAX(received_at) AS last_seen, AVG(payload_size) AS avg_payload_size
                FROM messages
                WHERE protocol IN ({placeholders})
                GROUP BY route
                ORDER BY count DESC
                LIMIT 20
                """,
                protocols,
            ).fetchall()
            minute_rows = self._conn.execute(
                f"""
                SELECT substr(received_at, 1, 16) AS minute, COUNT(*) AS count
                FROM messages
                WHERE protocol IN ({placeholders})
                GROUP BY minute
                ORDER BY minute DESC
                LIMIT 30
                """,
                protocols,
            ).fetchall()
            recent = self._conn.execute(
                f"""
                SELECT received_at, protocol, device_id, route, payload_size, sequence
                FROM messages
                WHERE protocol IN ({placeholders})
                ORDER BY received_at DESC
                LIMIT 20
                """,
                protocols,
            ).fetchall()
            device_rows = self._conn.execute(
                f"""
                SELECT device_id, protocol, last_route AS endpoint, last_source_ip AS peer,
                       last_seen_at AS last_seen, message_count, status, online,
                       last_interval_ms, avg_interval_ms, last_payload_size,
                       avg_payload_size, anomaly_count
                FROM device_state
                WHERE protocol IN ({placeholders})
                ORDER BY last_seen_at DESC
                LIMIT 50
                """,
                protocols,
            ).fetchall()
            route_missing = self._conn.execute(
                """
                SELECT COUNT(*) AS count FROM events
                WHERE event_type = 'route_missing' AND protocol IN ({})
                """.format(placeholders),
                protocols,
            ).fetchone()["count"]
            auth_failures = self._conn.execute(
                """
                SELECT COUNT(*) AS count FROM events
                WHERE event_type = 'auth_failure' AND protocol IN ({})
                """.format(placeholders),
                protocols,
            ).fetchone()["count"]
            return {
                "ok": True,
                "protocol_group": protocol_group,
                "total_messages": int(total or 0),
                "device_count": int(device_count or 0),
                "avg_payload_size": float(payload["avg_size"] or 0),
                "max_payload_size": int(payload["max_size"] or 0),
                "route_missing": int(route_missing or 0),
                "auth_failures": int(auth_failures or 0),
                "routes": [dict(row) for row in routes],
                "minute_series": [dict(row) for row in reversed(minute_rows)],
                "recent_messages": [dict(row) for row in recent],
                "devices": [_device_health(dict(row)) for row in device_rows],
            }

    def alert_events(self, limit: int = 100) -> list[dict[str, Any]]:
        self.open()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT created_at, severity, event_type, protocol, device_id, route, source, message, details_json
                FROM events
                WHERE severity IN ('warning', 'error', 'critical')
                   OR event_type IN ('auth_failure', 'route_missing', 'mqtt_disconnected')
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def alert_summary(self) -> dict[str, int]:
        self.open()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT severity, COUNT(*) AS count
                FROM events
                WHERE severity IN ('warning', 'error', 'critical')
                   OR event_type IN ('auth_failure', 'route_missing', 'mqtt_disconnected')
                GROUP BY severity
                """
            ).fetchall()
            result = {"warning": 0, "error": 0, "critical": 0, "total": 0}
            for row in rows:
                key = str(row["severity"] or "warning")
                result[key] = int(row["count"] or 0)
                result["total"] += int(row["count"] or 0)
            return result

    def export_events(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        self.open()
        where, params = _event_filter_sql(filters)
        limit = _limit(filters.get("limit"))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT created_at, severity, event_type, protocol, device_id, route, source, message, details_json
                FROM events
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def export_messages(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        self.open()
        where, params = _message_filter_sql(filters)
        limit = _limit(filters.get("limit"))
        include_payload = _truthy(filters.get("include_payload"))
        payload_columns = ", payload_json, payload_raw" if include_payload else ""
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT id, received_at, protocol, device_id, identity_source, source_ip, route,
                       endpoint_name, payload_type, payload_size, payload_hash, device_timestamp,
                       sequence, accepted, reject_reason, details_json
                       {payload_columns}
                FROM messages
                {where}
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                raw = item.get("payload_raw")
                if raw is not None:
                    item["payload_raw_hex"] = bytes(raw).hex()
                    item.pop("payload_raw", None)
                result.append(item)
            return result

    def _migrate_locked(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                protocol TEXT NOT NULL,
                device_id TEXT NOT NULL,
                identity_source TEXT NOT NULL,
                source_ip TEXT,
                route TEXT NOT NULL,
                endpoint_name TEXT,
                payload_type TEXT,
                payload_size INTEGER NOT NULL,
                payload_hash TEXT NOT NULL,
                payload_json TEXT,
                payload_raw BLOB,
                device_timestamp TEXT,
                sequence TEXT,
                accepted INTEGER NOT NULL,
                reject_reason TEXT,
                details_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_messages_received_at ON messages(received_at);
            CREATE INDEX IF NOT EXISTS idx_messages_device_id ON messages(device_id);
            CREATE INDEX IF NOT EXISTS idx_messages_protocol_route ON messages(protocol, route);

            CREATE TABLE IF NOT EXISTS device_state (
                device_id TEXT PRIMARY KEY,
                protocol TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_source_ip TEXT,
                last_route TEXT,
                last_sequence TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                avg_interval_ms REAL,
                last_interval_ms REAL,
                last_payload_size INTEGER,
                status TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_device_state_last_seen ON device_state(last_seen_at);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                protocol TEXT,
                device_id TEXT,
                route TEXT,
                source TEXT,
                message TEXT NOT NULL,
                details_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            """
        )
        self._ensure_columns_locked(
            "device_state",
            {
                "avg_payload_size": "REAL",
                "last_payload_hash": "TEXT",
                "online": "INTEGER NOT NULL DEFAULT 0",
                "last_connected_at": "TEXT",
                "last_disconnected_at": "TEXT",
                "anomaly_count": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        self._conn.commit()

    def _ensure_columns_locked(self, table: str, columns: dict[str, str]) -> None:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row["name"] for row in rows}
        for name, definition in columns.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _event_filter_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    _add_protocol_filter(clauses, params, filters)
    _add_eq(clauses, params, "device_id", filters.get("device_id"))
    _add_eq(clauses, params, "route", filters.get("route"))
    _add_eq(clauses, params, "event_type", filters.get("event_type"))
    _add_eq(clauses, params, "severity", filters.get("severity"))
    _add_range(clauses, params, "created_at", filters.get("from"), filters.get("to"))
    return ("WHERE " + " AND ".join(clauses), params) if clauses else ("", params)


def _message_filter_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    _add_protocol_filter(clauses, params, filters)
    _add_eq(clauses, params, "device_id", filters.get("device_id"))
    _add_eq(clauses, params, "route", filters.get("route"))
    _add_eq(clauses, params, "payload_type", filters.get("payload_type"))
    accepted = filters.get("accepted")
    if accepted is not None and str(accepted).strip() != "":
        clauses.append("accepted = ?")
        params.append(1 if str(accepted).lower() in {"1", "true", "yes", "accepted"} else 0)
    _add_range(clauses, params, "received_at", filters.get("from"), filters.get("to"))
    return ("WHERE " + " AND ".join(clauses), params) if clauses else ("", params)


def _add_protocol_filter(clauses: list[str], params: list[Any], filters: dict[str, Any]) -> None:
    group = str(filters.get("protocol_group") or "").lower()
    if group == "http":
        clauses.append("protocol IN (?, ?)")
        params.extend(["HTTP", "HTTPS"])
        return
    if group == "mqtt":
        clauses.append("protocol IN (?, ?)")
        params.extend(["MQTT", "MQTTS"])
        return
    _add_eq(clauses, params, "protocol", filters.get("protocol"))


def _add_eq(clauses: list[str], params: list[Any], column: str, value: Any) -> None:
    if value is None or str(value).strip() == "":
        return
    clauses.append(f"{column} = ?")
    params.append(str(value).upper() if column == "protocol" else str(value))


def _add_range(clauses: list[str], params: list[Any], column: str, from_value: Any, to_value: Any) -> None:
    if from_value:
        clauses.append(f"{column} >= ?")
        params.append(str(from_value))
    if to_value:
        clauses.append(f"{column} <= ?")
        params.append(str(to_value))


def _limit(value: Any) -> int:
    try:
        return max(1, min(100_000, int(value or 1000)))
    except (TypeError, ValueError):
        return 1000


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "include"}


def _device_health(row: dict[str, Any]) -> dict[str, Any]:
    last_seen = _parse_time(row.get("last_seen"))
    age_ms = None
    if last_seen is not None:
        age_ms = max(0.0, (datetime.now(UTC) - last_seen).total_seconds() * 1000.0)
    online = bool(row.get("online"))
    protocol = str(row.get("protocol") or "").upper()
    status = str(row.get("status") or "").lower()
    avg_interval = _as_float(row.get("avg_interval_ms"))
    stale_after = max(30_000.0, (avg_interval or 10_000.0) * 3.0)
    if protocol in {"MQTT", "MQTTS"} and online:
        health = "active"
        label = "Connected"
    elif protocol in {"MQTT", "MQTTS"} and status == "disconnected":
        health = "disconnected"
        label = "Disconnected"
    elif protocol in {"HTTP", "HTTPS"} and age_ms is not None and age_ms <= stale_after:
        health = "active"
        label = "Receiving data"
    elif age_ms is not None and age_ms <= stale_after:
        health = "recent"
        label = "Recently seen"
    elif age_ms is not None and age_ms <= stale_after * 4:
        health = "recent"
        label = "Recently seen"
    else:
        health = "stale"
        label = "No recent data"
    row["health"] = health
    row["health_label"] = label
    row["last_seen_age_ms"] = age_ms
    return row


def _anomaly_events(record: dict[str, Any], existing: dict[str, Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    device_id = str(record.get("device_id") or "unknown")
    protocol = str(record.get("protocol") or "")
    route = str(record.get("route") or "")
    received_at = str(record.get("received_at") or "")
    now_dt = _parse_time(received_at)
    if existing is None:
        events.append(_event("info", "new_device", protocol, device_id, route, f"New device seen: {device_id}"))
        return events

    last_seen_dt = _parse_time(existing.get("last_seen_at"))
    interval_ms = _interval_ms(last_seen_dt, now_dt)
    avg_interval_ms = _as_float(existing.get("avg_interval_ms"))
    message_count = int(existing.get("message_count") or 0)
    if interval_ms is not None and avg_interval_ms and message_count >= 3:
        if interval_ms > max(5000.0, avg_interval_ms * 3.0):
            events.append(_event(
                "warning",
                "message_gap",
                protocol,
                device_id,
                route,
                f"Message gap high for {device_id}: {int(interval_ms)} ms",
                {"interval_ms": interval_ms, "avg_interval_ms": avg_interval_ms},
            ))
            events.append(_event(
                "warning",
                "rate_slowdown",
                protocol,
                device_id,
                route,
                f"Message rate slowed for {device_id}",
                {"interval_ms": interval_ms, "avg_interval_ms": avg_interval_ms},
            ))
        elif message_count >= 10 and interval_ms < avg_interval_ms * 0.25:
            events.append(_event(
                "info",
                "rate_spike",
                protocol,
                device_id,
                route,
                f"Message rate spiked for {device_id}",
                {"interval_ms": interval_ms, "avg_interval_ms": avg_interval_ms},
            ))

    payload_size = int(record.get("payload_size") or 0)
    avg_payload_size = _as_float(existing.get("avg_payload_size"))
    if avg_payload_size and avg_payload_size > 0 and message_count >= 3:
        ratio = abs(payload_size - avg_payload_size) / avg_payload_size
        if ratio > 0.5:
            events.append(_event(
                "warning",
                "payload_size_change",
                protocol,
                device_id,
                route,
                f"Payload size changed for {device_id}",
                {"payload_size": payload_size, "avg_payload_size": avg_payload_size, "ratio": ratio},
            ))

    sequence = record.get("sequence")
    last_sequence = existing.get("last_sequence")
    if sequence is not None and last_sequence is not None:
        sequence_text = str(sequence)
        last_sequence_text = str(last_sequence)
        if sequence_text == last_sequence_text:
            events.append(_event("warning", "sequence_duplicate", protocol, device_id, route, f"Duplicate sequence from {device_id}: {sequence_text}"))
        else:
            current_int = _as_int(sequence_text)
            last_int = _as_int(last_sequence_text)
            if current_int is not None and last_int is not None and current_int < last_int:
                events.append(_event(
                    "warning",
                    "sequence_out_of_order",
                    protocol,
                    device_id,
                    route,
                    f"Out-of-order sequence from {device_id}: {current_int} after {last_int}",
                    {"sequence": current_int, "last_sequence": last_int},
                ))

    device_timestamp = _parse_time(record.get("device_timestamp"))
    if device_timestamp is not None and now_dt is not None:
        drift_ms = abs((now_dt - device_timestamp).total_seconds() * 1000.0)
        if drift_ms > 300_000:
            events.append(_event(
                "warning",
                "device_clock_drift",
                protocol,
                device_id,
                route,
                f"Device clock drift high for {device_id}",
                {"drift_ms": drift_ms, "device_timestamp": record.get("device_timestamp"), "received_at": received_at},
            ))
        stale_ms = (now_dt - device_timestamp).total_seconds() * 1000.0
        if stale_ms > 300_000:
            events.append(_event(
                "warning",
                "device_timestamp_stale",
                protocol,
                device_id,
                route,
                f"Device timestamp stale for {device_id}",
                {"stale_ms": stale_ms, "device_timestamp": record.get("device_timestamp"), "received_at": received_at},
            ))
    return events


def _event(
    severity: str,
    event_type: str,
    protocol: str,
    device_id: str,
    route: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": _utc_now(),
        "severity": severity,
        "type": event_type,
        "event_type": event_type,
        "protocol": protocol,
        "device_id": device_id,
        "route": route,
        "source": device_id,
        "message": message,
        "details": details or {},
    }


def _rolling_avg(previous: Any, current: float | int | None) -> float | None:
    if current is None:
        return _as_float(previous)
    previous_value = _as_float(previous)
    if previous_value is None:
        return float(current)
    return previous_value * 0.8 + float(current) * 0.2


def _interval_ms(previous: datetime | None, current: datetime | None) -> float | None:
    if previous is None or current is None:
        return None
    return max(0.0, (current - previous).total_seconds() * 1000.0)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
