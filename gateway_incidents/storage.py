"""Durable storage for correlated incidents.

An incident is the customer-facing unit: one continuity problem, opened when
it starts and closed only once the affected path has recovered and stayed
stable. The raw events it was built from stay where they are — this table is a
correlation layer above them, not a replacement.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("/opt/metacrust/data/incidents/incidents.db")
DEFAULT_RETENTION_DAYS = 180
VACUUM_FREE_BYTES = 16 * 1024 * 1024


class IncidentStorage:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("METACRUST_INCIDENTS_DB_PATH") or DEFAULT_DB_PATH)
        self.retention_days = max(1, int(os.environ.get("METACRUST_INCIDENTS_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)))
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # ── lifecycle ────────────────────────────────────────────────────────
    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
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
            CREATE TABLE IF NOT EXISTS incidents (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ref             TEXT NOT NULL UNIQUE,
                scope_kind      TEXT NOT NULL,
                scope_key       TEXT NOT NULL,
                title           TEXT NOT NULL,
                status          TEXT NOT NULL,
                started_ms      INTEGER NOT NULL,
                detected_ms     INTEGER NOT NULL,
                restored_ms     INTEGER,
                closed_ms       INTEGER,
                domain          TEXT NOT NULL,
                domain_conf     TEXT NOT NULL,
                severity        TEXT NOT NULL,
                affected_json   TEXT NOT NULL,
                evidence_json   TEXT NOT NULL,
                continuity_json TEXT NOT NULL,
                timeline_json   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_incidents_started ON incidents (started_ms);
            CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents (status, started_ms);
            -- One row per scope may be open at a time; the correlator looks it
            -- up on every pass to decide extend-vs-open.
            CREATE INDEX IF NOT EXISTS idx_incidents_scope ON incidents (scope_kind, scope_key, status);
            """
        )
        # kpi_json arrived after the first incidents were recorded, so it is added
        # by migration rather than in the CREATE above.
        self._ensure_columns_locked("incidents", {"kpi_json": "TEXT"})
        # Which lifecycle state the operator has been told about. Kept here, not
        # in the notifier's memory, so a restart neither re-announces incidents
        # nor silently drops ones that opened just before it.
        if self._ensure_columns_locked("incidents", {"notified_state": "TEXT"}):
            # Incidents that predate this column were handled by the old
            # in-memory notifier; treat them as already announced.
            self._conn.execute("UPDATE incidents SET notified_state = status WHERE notified_state IS NULL")
        if self._ensure_columns_locked("incidents", {"notified_domain": "TEXT"}):
            # Whatever was announced before this column existed named the
            # diagnosis of the time, which is the stored one.
            self._conn.execute(
                "UPDATE incidents SET notified_domain = domain WHERE notified_state IS NOT NULL"
            )
        self._conn.commit()

    def _ensure_columns_locked(self, table: str, columns: dict[str, str]) -> bool:
        """Add missing columns; returns whether any were added."""
        assert self._conn is not None
        existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
        added = False
        for name, definition in columns.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                added = True
        return added

    def mark_notified(self, incident_id: int, state: str, domain: str | None = None) -> None:
        """Record what readers were last told: the state, and the diagnosis
        stated with it, so a later change of diagnosis can be corrected."""
        with self._lock:
            self.open()
            assert self._conn is not None
            if domain is None:
                self._conn.execute("UPDATE incidents SET notified_state = ? WHERE id = ?", (state, int(incident_id)))
            else:
                self._conn.execute(
                    "UPDATE incidents SET notified_state = ?, notified_domain = ? WHERE id = ?",
                    (state, domain, int(incident_id)),
                )
            self._conn.commit()

    # ── writes ───────────────────────────────────────────────────────────
    def open_incident(self, incident: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.open()
            assert self._conn is not None
            cursor = self._conn.execute(
                """INSERT INTO incidents
                   (ref, scope_kind, scope_key, title, status, started_ms, detected_ms,
                    restored_ms, closed_ms, domain, domain_conf, severity,
                    affected_json, evidence_json, continuity_json, timeline_json, kpi_json)
                   VALUES (?, ?, ?, ?, 'open', ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    incident["ref"], incident["scope_kind"], incident["scope_key"],
                    incident["title"], int(incident["started_ms"]), int(incident["detected_ms"]),
                    incident["domain"], incident["domain_conf"], incident["severity"],
                    _json(incident.get("affected", [])), _json(incident.get("evidence", [])),
                    _json(incident.get("continuity", {})), _json(incident.get("timeline", [])),
                    _json(incident.get("kpi", {})),
                ),
            )
            self._conn.commit()
            incident["id"] = int(cursor.lastrowid)
            return incident

    def update_incident(self, incident_id: int, fields: dict[str, Any]) -> None:
        """Patch a live incident. JSON-valued keys are encoded automatically."""
        if not fields:
            return
        columns: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            columns.append(f"{key} = ?")
            values.append(_json(value) if key.endswith("_json") else value)
        values.append(int(incident_id))
        with self._lock:
            self.open()
            assert self._conn is not None
            self._conn.execute(f"UPDATE incidents SET {', '.join(columns)} WHERE id = ?", values)
            self._conn.commit()

    def next_ref(self) -> str:
        """Sequential customer-facing reference (MC-1042), stable once issued."""
        with self._lock:
            self.open()
            assert self._conn is not None
            row = self._conn.execute("SELECT COALESCE(MAX(id), 0) AS last FROM incidents").fetchone()
            return f"MC-{1000 + int(row['last'] or 0) + 1}"

    # ── reads ────────────────────────────────────────────────────────────
    def open_incidents(self) -> list[dict[str, Any]]:
        """Everything not yet closed, so the UI surfaces incidents that are
        still confirming their recovery as well as actively failing ones."""
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                """SELECT * FROM incidents WHERE status IN ('open', 'recovering')
                   ORDER BY started_ms DESC LIMIT 200"""
            ).fetchall()
            return [_row_to_incident(row) for row in rows]

    def open_for_scope(self, scope_kind: str, scope_key: str) -> dict[str, Any] | None:
        """The live incident for a scope, if any.

        'recovering' counts as live: it is still inside the stability window,
        so the correlator must keep finding it — both to close it once the
        window passes, and to reopen it rather than start a duplicate if the
        fault comes back.
        """
        with self._lock:
            self.open()
            assert self._conn is not None
            row = self._conn.execute(
                """SELECT * FROM incidents
                   WHERE scope_kind = ? AND scope_key = ? AND status IN ('open', 'recovering')
                   ORDER BY started_ms DESC LIMIT 1""",
                (scope_kind, scope_key),
            ).fetchone()
            return _row_to_incident(row) if row else None

    def query(
        self, *, status: str | None = None, domain: str | None = None,
        from_ms: int = 0, to_ms: int = 2**63 - 1, limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["started_ms >= ?", "started_ms <= ?"]
        values: list[Any] = [int(from_ms), int(to_ms)]
        if status:
            clauses.append("status = ?")
            values.append(status)
        if domain:
            clauses.append("domain = ?")
            values.append(domain)
        values.append(max(1, min(int(limit), 1000)))
        with self._lock:
            self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                f"""SELECT * FROM incidents WHERE {' AND '.join(clauses)}
                    ORDER BY started_ms DESC LIMIT ?""",
                values,
            ).fetchall()
            return [_row_to_incident(row) for row in rows]

    def by_ref(self, ref: str) -> dict[str, Any] | None:
        with self._lock:
            self.open()
            assert self._conn is not None
            row = self._conn.execute("SELECT * FROM incidents WHERE ref = ?", (ref,)).fetchone()
            return _row_to_incident(row) if row else None

    def summary(self, since_ms: int) -> dict[str, Any]:
        with self._lock:
            self.open()
            assert self._conn is not None
            open_row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM incidents WHERE status = 'open'"
            ).fetchone()
            window_rows = self._conn.execute(
                """SELECT domain, COUNT(*) AS n FROM incidents
                   WHERE started_ms >= ? GROUP BY domain""",
                (int(since_ms),),
            ).fetchall()
        return {
            "open_count": int(open_row["n"] if open_row else 0),
            "by_domain": {row["domain"]: int(row["n"]) for row in window_rows},
            "window_count": sum(int(row["n"]) for row in window_rows),
        }

    # ── maintenance ──────────────────────────────────────────────────────
    def maintain(self) -> None:
        """Drop resolved incidents past the retention window. Runs on a worker
        thread with the other storage maintenance, never on the event loop."""
        with self._lock:
            self.open()
            assert self._conn is not None
            cutoff = int(time.time() * 1000) - self.retention_days * 86_400_000
            self._conn.execute(
                "DELETE FROM incidents WHERE status = 'resolved' AND started_ms < ?", (cutoff,)
            )
            self._conn.commit()
            page_size = int(self._conn.execute("PRAGMA page_size").fetchone()[0])
            free_bytes = int(self._conn.execute("PRAGMA freelist_count").fetchone()[0]) * page_size
            if free_bytes >= VACUUM_FREE_BYTES:
                self._conn.commit()
                self._conn.execute("VACUUM")


def _row_to_incident(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for key, target in (
        ("affected_json", "affected"), ("evidence_json", "evidence"),
        ("continuity_json", "continuity"), ("timeline_json", "timeline"),
        ("kpi_json", "kpi"),
    ):
        item[target] = _load(item.pop(key))
    return item


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _load(text: Any) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return []
