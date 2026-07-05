"""SQLite-backed storage for device-monitor time series and anomaly events.

The C++ gateway_core anomaly engine streams two things over IPC:
  * deviceData      - raw device metrics, once per second
  * deviceAnamoly   - anomaly events, only when something actually fires

Both feed the Monitor > Anomaly charts, so both must survive a hub restart.
To keep the eMMC happy we never store raw 1 Hz samples: metric values are
aggregated into fixed time buckets (avg/min/max) before they hit disk.

Two resolution tiers share one table:
  * 'fine'   - 15 s buckets, kept 3 days   -> smooth zoom around an anomaly
  * 'hourly' - 1 h buckets, kept 31 days   -> the month-long overview

min/max are preserved per bucket so a short spike is never averaged away.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("gateway_ipc")

DEFAULT_DB_PATH = Path("/opt/metacrust/data/monitor/monitor.db")
DEFAULT_SQLITE_PATH = Path.home() / ".metacrust" / "data" / "monitor" / "monitor.sqlite3"

FINE_BUCKET_MS = 15_000            # 15 second fine buckets
HOURLY_BUCKET_MS = 3_600_000       # 1 hour coarse buckets
FINE_RETENTION_MS = 3 * 86_400_000        # keep fine buckets 3 days
HOURLY_RETENTION_MS = 31 * 86_400_000     # keep hourly buckets 31 days
ANOMALY_RETENTION_MS = 31 * 86_400_000    # keep anomaly events 31 days

# Range at/under which the fine tier is used; above it we serve hourly.
FINE_QUERY_MAX_MS = 2 * 86_400_000

# The metrics that get their own chart. Keys match the C++ metricName strings
# so anomaly events overlay straight onto the matching chart.
CHART_METRICS = (
    "cpu.usage",
    "cpu.temp",
    "memory.ram_used_pct",
    "storage.disk_used_pct",
    "storage.emmc_used_pct",
    "cpu.load_1m",
)


@dataclass
class _Bucket:
    """In-memory accumulator for the current fine bucket of one metric."""

    total: float = 0.0
    count: int = 0
    minimum: float = field(default=float("inf"))
    maximum: float = field(default=float("-inf"))

    def add(self, value: float) -> None:
        self.total += value
        self.count += 1
        if value < self.minimum:
            self.minimum = value
        if value > self.maximum:
            self.maximum = value


class MonitorStorage:
    def __init__(self, db_path: Path | None = None) -> None:
        configured = db_path or os.environ.get("METACRUST_MONITOR_DB_PATH")
        self.db_path = Path(configured) if configured else DEFAULT_SQLITE_PATH
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        # bucket_ms -> {metric -> _Bucket}; usually holds a single open bucket.
        self._pending: dict[int, dict[str, _Bucket]] = {}
        self._last_maintenance_ms = 0

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
            LOGGER.info("monitor_storage_open path=%s", self.db_path)

    def close(self) -> None:
        with self._lock:
            if self._conn is None:
                return
            self._flush_ready_buckets_locked(flush_all=True)
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def _migrate_locked(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metric_rollup (
                metric     TEXT    NOT NULL,
                tier       TEXT    NOT NULL,
                bucket_ms  INTEGER NOT NULL,
                avg        REAL    NOT NULL,
                min        REAL    NOT NULL,
                max        REAL    NOT NULL,
                samples    INTEGER NOT NULL,
                PRIMARY KEY (metric, tier, bucket_ms)
            );
            CREATE INDEX IF NOT EXISTS idx_metric_rollup_query
                ON metric_rollup (metric, tier, bucket_ms);

            CREATE TABLE IF NOT EXISTS anomaly_events (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms          INTEGER NOT NULL,
                metric         TEXT,
                detector       TEXT,
                severity       TEXT,
                value          REAL,
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
            CREATE INDEX IF NOT EXISTS idx_anomaly_ts
                ON anomaly_events (ts_ms);
            CREATE INDEX IF NOT EXISTS idx_anomaly_metric_ts
                ON anomaly_events (metric, ts_ms);
            """
        )
        self._conn.commit()

    # ── ingestion ────────────────────────────────────────────────────────
    def add_metric_sample(self, values: dict[str, float], timestamp_ms: int) -> None:
        """Accumulate one 1 Hz metric reading into its fine bucket.

        `values` maps C++ metricName -> value. Only CHART_METRICS are stored.
        """
        if not values:
            return
        bucket = (int(timestamp_ms) // FINE_BUCKET_MS) * FINE_BUCKET_MS
        with self._lock:
            if self._conn is None:
                self.open()
            bucket_metrics = self._pending.setdefault(bucket, {})
            for metric, value in values.items():
                if metric not in CHART_METRICS:
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                bucket_metrics.setdefault(metric, _Bucket()).add(numeric)
            # Flush any bucket that is now in the past so disk writes stay small
            # and one open bucket is held in memory at a time.
            self._flush_ready_buckets_locked(flush_all=False)
            self._maybe_maintain_locked(timestamp_ms)

    def add_anomaly_events(self, events: list[dict[str, Any]]) -> None:
        """Persist a batch of normalized anomaly events (see message_protocol)."""
        if not events:
            return
        with self._lock:
            if self._conn is None:
                self.open()
            assert self._conn is not None
            self._conn.executemany(
                """
                INSERT INTO anomaly_events (
                    ts_ms, metric, detector, severity, value,
                    warning_limit, critical_limit, min_value, max_value,
                    alarm_name, category, metric_label, headline, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        int(ev.get("timestamp_ms") or 0),
                        ev.get("metric"),
                        ev.get("detector"),
                        ev.get("severity"),
                        _opt_float(ev.get("value")),
                        _opt_float(ev.get("warning_limit")),
                        _opt_float(ev.get("critical_limit")),
                        _opt_float(ev.get("min_value")),
                        _opt_float(ev.get("max_value")),
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

    def _flush_ready_buckets_locked(self, *, flush_all: bool) -> None:
        assert self._conn is not None
        current_bucket = (int(time.time() * 1000) // FINE_BUCKET_MS) * FINE_BUCKET_MS
        ready = [b for b in self._pending if flush_all or b < current_bucket]
        if not ready:
            return
        rows = []
        for bucket in ready:
            for metric, acc in self._pending.pop(bucket).items():
                if acc.count == 0:
                    continue
                rows.append((metric, "fine", bucket, acc.total / acc.count, acc.minimum, acc.maximum, acc.count))
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT INTO metric_rollup (metric, tier, bucket_ms, avg, min, max, samples)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(metric, tier, bucket_ms) DO UPDATE SET
                avg     = excluded.avg,
                min     = excluded.min,
                max     = excluded.max,
                samples = excluded.samples
            """,
            rows,
        )
        self._conn.commit()

    # ── maintenance: downsample + prune ──────────────────────────────────
    def _maybe_maintain_locked(self, now_ms: int) -> None:
        # Run at most once per 10 minutes.
        if now_ms - self._last_maintenance_ms < 600_000:
            return
        self._last_maintenance_ms = now_ms
        self._downsample_locked(now_ms)
        self._prune_locked(now_ms)

    def _downsample_locked(self, now_ms: int) -> None:
        assert self._conn is not None
        # Rebuild hourly buckets from the last 3 days of fine data (cheap, and
        # covers hours that are about to lose their fine rows to pruning).
        since = now_ms - FINE_RETENTION_MS
        self._conn.execute(
            """
            INSERT INTO metric_rollup (metric, tier, bucket_ms, avg, min, max, samples)
            SELECT metric,
                   'hourly',
                   (bucket_ms / ?) * ? AS hb,
                   SUM(avg * samples) / SUM(samples),
                   MIN(min),
                   MAX(max),
                   SUM(samples)
            FROM metric_rollup
            WHERE tier = 'fine' AND bucket_ms >= ?
            GROUP BY metric, hb
            ON CONFLICT(metric, tier, bucket_ms) DO UPDATE SET
                avg     = excluded.avg,
                min     = excluded.min,
                max     = excluded.max,
                samples = excluded.samples
            """,
            (HOURLY_BUCKET_MS, HOURLY_BUCKET_MS, since),
        )
        self._conn.commit()

    def _prune_locked(self, now_ms: int) -> None:
        assert self._conn is not None
        self._conn.execute(
            "DELETE FROM metric_rollup WHERE tier = 'fine' AND bucket_ms < ?",
            (now_ms - FINE_RETENTION_MS,),
        )
        self._conn.execute(
            "DELETE FROM metric_rollup WHERE tier = 'hourly' AND bucket_ms < ?",
            (now_ms - HOURLY_RETENTION_MS,),
        )
        self._conn.execute(
            "DELETE FROM anomaly_events WHERE ts_ms < ?",
            (now_ms - ANOMALY_RETENTION_MS,),
        )
        self._conn.commit()

    # ── queries ──────────────────────────────────────────────────────────
    def timeseries(self, metric: str, from_ms: int, to_ms: int) -> dict[str, Any]:
        """Return chart points + overlaid anomalies for one metric/time range."""
        with self._lock:
            if self._conn is None:
                self.open()
            assert self._conn is not None
            # Make sure the newest completed bucket is visible before querying.
            self._flush_ready_buckets_locked(flush_all=False)
            span = max(0, int(to_ms) - int(from_ms))
            tier = "fine" if span <= FINE_QUERY_MAX_MS else "hourly"
            point_rows = self._conn.execute(
                """
                SELECT bucket_ms, avg, min, max
                FROM metric_rollup
                WHERE metric = ? AND tier = ? AND bucket_ms >= ? AND bucket_ms <= ?
                ORDER BY bucket_ms ASC
                """,
                (metric, tier, int(from_ms), int(to_ms)),
            ).fetchall()
            anomaly_rows = self._conn.execute(
                """
                SELECT ts_ms, severity, value, category, metric_label,
                       headline, message, detector, warning_limit, critical_limit
                FROM anomaly_events
                WHERE metric = ? AND ts_ms >= ? AND ts_ms <= ?
                ORDER BY ts_ms ASC
                """,
                (metric, int(from_ms), int(to_ms)),
            ).fetchall()
        return {
            "metric": metric,
            "tier": tier,
            "points": [
                {"t": row["bucket_ms"], "avg": row["avg"], "min": row["min"], "max": row["max"]}
                for row in point_rows
            ],
            "anomalies": [dict(row) for row in anomaly_rows],
        }

    def recent_anomalies(self, since_ms: int, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            if self._conn is None:
                self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                """
                SELECT ts_ms, metric, detector, severity, value, category,
                       metric_label, headline, message, alarm_name
                FROM anomaly_events
                WHERE ts_ms >= ?
                ORDER BY ts_ms DESC
                LIMIT ?
                """,
                (int(since_ms), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def grouped_anomalies(self, since_ms: int) -> list[dict[str, Any]]:
        """Collapse the anomaly flood into one row per (metric, category, severity).

        The engine can fire the same finding every second; a raw list is useless.
        This returns a de-duplicated summary with a count, value range, and the
        most recent occurrence, ordered by how recently each issue last fired.
        """
        with self._lock:
            if self._conn is None:
                self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                """
                SELECT metric, metric_label, category, severity,
                       COUNT(*)     AS count,
                       MAX(ts_ms)   AS latest_ts,
                       MIN(value)   AS min_value,
                       MAX(value)   AS max_value,
                       (SELECT value FROM anomaly_events e2
                          WHERE e2.metric IS e1.metric
                            AND e2.category IS e1.category
                            AND e2.severity IS e1.severity
                            AND e2.ts_ms >= ?
                          ORDER BY e2.ts_ms DESC LIMIT 1) AS latest_value,
                       (SELECT headline FROM anomaly_events e3
                          WHERE e3.metric IS e1.metric
                            AND e3.category IS e1.category
                            AND e3.severity IS e1.severity
                            AND e3.ts_ms >= ?
                          ORDER BY e3.ts_ms DESC LIMIT 1) AS latest_headline
                FROM anomaly_events e1
                WHERE ts_ms >= ?
                GROUP BY metric, category, severity
                ORDER BY latest_ts DESC
                """,
                (int(since_ms), int(since_ms), int(since_ms)),
            ).fetchall()
        return [dict(row) for row in rows]

    def anomaly_counts(self, since_ms: int) -> dict[str, int]:
        with self._lock:
            if self._conn is None:
                self.open()
            assert self._conn is not None
            rows = self._conn.execute(
                """
                SELECT severity, COUNT(*) AS n
                FROM anomaly_events
                WHERE ts_ms >= ?
                GROUP BY severity
                """,
                (int(since_ms),),
            ).fetchall()
        counts = {"Info": 0, "Warning": 0, "Critical": 0, "total": 0}
        for row in rows:
            sev = row["severity"] or "Info"
            counts[sev] = counts.get(sev, 0) + row["n"]
            counts["total"] += row["n"]
        return counts


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
