"""Forwarding runtime state: per-profile cursors, delivery counters, event log.

The forwarder does NOT keep its own copy of outgoing data — sensor data and
anomaly events are already durably stored by gateway_interfaces / the monitor
store. Delivery progress is just a cursor (last forwarded row id) per profile
and stream; an uplink outage simply leaves the cursor behind and replay is
"continue from cursor".
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("/opt/metacrust/data/forwarding/forwarding.db")
FALLBACK_DB_PATH = Path.home() / ".metacrust" / "data" / "forwarding" / "forwarding.db"

EVENT_RETENTION_MS = 31 * 86_400_000


class ForwardingStorage:
    def __init__(self, db_path: Path | str | None = None) -> None:
        configured = db_path or os.environ.get("METACRUST_FORWARDING_DB_PATH")
        if configured:
            self.db_path = Path(configured)
        else:
            parent_ok = False
            for candidate in (DEFAULT_DB_PATH.parent, *DEFAULT_DB_PATH.parent.parents):
                if candidate.exists():
                    parent_ok = os.access(candidate, os.W_OK)
                    break
            self.db_path = DEFAULT_DB_PATH if parent_ok else FALLBACK_DB_PATH
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cursors (
                    profile_id TEXT NOT NULL,
                    stream     TEXT NOT NULL,
                    last_id    INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (profile_id, stream)
                );
                CREATE TABLE IF NOT EXISTS counters (
                    profile_id   TEXT PRIMARY KEY,
                    sent         INTEGER NOT NULL DEFAULT 0,
                    replayed     INTEGER NOT NULL DEFAULT 0,
                    dropped      INTEGER NOT NULL DEFAULT 0,
                    last_sent_ms INTEGER
                );
                CREATE TABLE IF NOT EXISTS events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ms      INTEGER NOT NULL,
                    profile_id TEXT NOT NULL,
                    severity   TEXT NOT NULL,
                    event      TEXT NOT NULL,
                    message    TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fwd_events_ts ON events (ts_ms);
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            self._conn.commit()
            self._conn.close()
            self._conn = None

    # ── cursors ──────────────────────────────────────────────────────────
    def get_cursor(self, profile_id: str, stream: str) -> int:
        with self._lock:
            self.open()
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT last_id FROM cursors WHERE profile_id = ? AND stream = ?",
                (profile_id, stream),
            ).fetchone()
            return int(row["last_id"]) if row else 0

    def set_cursor(self, profile_id: str, stream: str, last_id: int) -> None:
        with self._lock:
            self.open()
            assert self._conn is not None
            self._conn.execute(
                """
                INSERT INTO cursors (profile_id, stream, last_id) VALUES (?, ?, ?)
                ON CONFLICT(profile_id, stream) DO UPDATE SET last_id = excluded.last_id
                """,
                (profile_id, stream, int(last_id)),
            )
            self._conn.commit()

    # ── counters ─────────────────────────────────────────────────────────
    def bump(self, profile_id: str, sent: int = 0, replayed: int = 0, dropped: int = 0) -> None:
        with self._lock:
            self.open()
            assert self._conn is not None
            self._conn.execute(
                """
                INSERT INTO counters (profile_id, sent, replayed, dropped, last_sent_ms)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    sent = sent + excluded.sent,
                    replayed = replayed + excluded.replayed,
                    dropped = dropped + excluded.dropped,
                    last_sent_ms = CASE WHEN excluded.sent > 0 THEN excluded.last_sent_ms ELSE last_sent_ms END
                """,
                (profile_id, int(sent), int(replayed), int(dropped), int(time.time() * 1000)),
            )
            self._conn.commit()

    def counters(self, profile_id: str) -> dict[str, Any]:
        with self._lock:
            self.open()
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT sent, replayed, dropped, last_sent_ms FROM counters WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        if not row:
            return {"sent": 0, "replayed": 0, "dropped": 0, "last_sent_ms": None}
        return dict(row)

    # ── events ───────────────────────────────────────────────────────────
    def add_event(self, profile_id: str, severity: str, event: str, message: str) -> None:
        now_ms = int(time.time() * 1000)
        with self._lock:
            self.open()
            assert self._conn is not None
            self._conn.execute(
                "INSERT INTO events (ts_ms, profile_id, severity, event, message) VALUES (?, ?, ?, ?, ?)",
                (now_ms, profile_id, severity, event, message[:500]),
            )
            self._conn.execute("DELETE FROM events WHERE ts_ms < ?", (now_ms - EVENT_RETENTION_MS,))
            self._conn.commit()

    def recent_events(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                "SELECT ts_ms, profile_id, severity, event, message FROM events ORDER BY ts_ms DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]
