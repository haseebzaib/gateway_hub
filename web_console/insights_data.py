from __future__ import annotations

import json
import os
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gateway_interfaces import GatewayInterfacesDataStorage

# A reading younger than FRESH_MS is "good" (assuming the source itself is
# online); older than STALE_MS but the source is still online is "stale".
# Beyond that with no source update at all, the device has no /live entry
# and the page shows it "Offline" — see build_live_devices().
FRESH_MS = 8_000
STALE_MS = 30_000

WINDOW_MS = {"1h": 3_600_000, "6h": 21_600_000, "24h": 86_400_000, "7d": 604_800_000}
STATS_WINDOW_MS = {"5min": 300_000, "1hr": 3_600_000, "24hr": 86_400_000}
TARGET_BUCKETS = 180
TREND_LOOKBACK_MS = 300_000  # trends are computed from the last ~5 min of data

DEFAULT_ALERT_RULES_PATH = Path(
    os.environ.get("METACRUST_INSIGHTS_RULES_PATH", "/opt/metacrust/config/gateway_insights/alert_rules.json")
)
EVENT_GROUP_GAP_MS = 60_000
MAX_EVENTS_MEMORY = 2000


def _iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Configured devices — derived from the enabled rs232/rs485/modbus_tcp config.
# Metric lists come from the config's own register declarations when present
# (modbus_tcp/modbus_rtu); RS232 sensor config doesn't declare registers up
# front, so those fall back to whatever metric names have actually been seen
# in the database.
# ---------------------------------------------------------------------------

def configured_devices(interfaces_config: dict[str, Any], storage: GatewayInterfacesDataStorage) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []

    for port_name, port in (interfaces_config.get("rs232") or {}).items():
        if not port.get("enabled") or port.get("mode") != "sensor":
            continue
        sensor = port.get("sensor") or "sensor"
        metrics = storage.distinct_reading_names("rs232Sensor", port_name)
        devices.append({
            "source": "rs232Sensor", "device_id": port_name, "name": f"RS232 {port_name} ({sensor})",
            "device_type": sensor, "poll_interval_ms": 1000,
            "transport": {"type": "serial", "endpoint": port_name},
            "expected_metrics": metrics,
        })

    for port_name, port in (interfaces_config.get("rs485") or {}).items():
        if not port.get("enabled"):
            continue
        rtu = port.get("modbus_rtu") or {}
        metrics = [{"name": r["name"], "unit": r.get("unit", "")} for r in (rtu.get("registers") or []) if r.get("name")]
        if not metrics:
            metrics = storage.distinct_reading_names("modbusRtu", port_name)
        devices.append({
            "source": "modbusRtu", "device_id": port_name, "name": f"Modbus RTU {port_name}",
            "device_type": "modbus_rtu", "poll_interval_ms": rtu.get("poll_interval_ms", 1000),
            "transport": {"type": "modbus_rtu", "endpoint": port_name},
            "expected_metrics": metrics,
        })

    for conn in (interfaces_config.get("modbus_tcp") or {}).get("connections", []):
        if not conn.get("enabled"):
            continue
        device_id = conn.get("id", "")
        metrics = [{"name": r["name"], "unit": r.get("unit", "")} for r in (conn.get("registers") or []) if r.get("name")]
        if not metrics:
            metrics = storage.distinct_reading_names("modbusTcp", device_id)
        devices.append({
            "source": "modbusTcp", "device_id": device_id, "name": conn.get("name") or device_id,
            "device_type": "modbus_tcp", "poll_interval_ms": conn.get("poll_interval_ms", 1000),
            "transport": {
                "type": "modbus_tcp", "endpoint": conn.get("ip", ""),
                "port": conn.get("port", 502), "interface": conn.get("interface", "eth0"),
            },
            "expected_metrics": metrics,
        })

    return devices


# ---------------------------------------------------------------------------
# Live snapshot — latest reading per metric + freshness-based quality.
# ---------------------------------------------------------------------------

def _quality_for(age_ms: float, source_status: str) -> str:
    if source_status == "error":
        return "error"
    return "good" if age_ms <= FRESH_MS else "stale"


def build_live_devices(devices: list[dict[str, Any]], storage: GatewayInterfacesDataStorage) -> list[dict[str, Any]]:
    now_ms = int(time.time() * 1000)
    sources_by_key = {(s["source_type"], s["source_id"]): s for s in storage.sources()}
    live: list[dict[str, Any]] = []

    for device in devices:
        key = (device["source"], device["device_id"])
        source_row = sources_by_key.get(key)
        if source_row is None:
            continue  # never seen at all -> no /live entry, page shows "Offline"

        latest = storage.latest_readings(*key)
        metrics: dict[str, Any] = {}
        samples: dict[str, list[float]] = {}
        for m in device["expected_metrics"]:
            row = latest.get(m["name"])
            if row is None:
                continue
            age_ms = now_ms - int(row["ts_ms"])
            quality = _quality_for(age_ms, source_row["last_status"])
            metrics[m["name"]] = {"value": row["value"], "unit": row["unit"] or m.get("unit", ""), "quality": quality}
            samples[m["name"]] = storage.recent_values(*key, m["name"], limit=20)

        last_status = source_row["last_status"]
        if last_status == "error":
            status = "error"
        elif metrics and all(m["quality"] == "good" for m in metrics.values()):
            status = "ok"
        else:
            status = "warning"
        error = {"type": "source_error", "message": source_row["last_error"]} if last_status == "error" and source_row["last_error"] else None

        live.append({
            "source": device["source"], "device_id": device["device_id"],
            "status": status, "timestamp_ms": source_row["last_seen_ms"],
            "error": error, "metrics": metrics, "_samples": samples,
        })

    return live


def summary(devices: list[dict[str, Any]], live: list[dict[str, Any]]) -> dict[str, Any]:
    configured_count = len(devices)
    total_metrics = good_metrics = ok_devices = anomaly_count = 0
    for d in live:
        device_ok = d["status"] == "ok" and not d.get("error")
        metrics = d.get("metrics") or {}
        if not metrics:
            total_metrics += 1
        else:
            for m in metrics.values():
                total_metrics += 1
                if device_ok and m.get("value") is not None and m.get("quality") == "good":
                    good_metrics += 1
        if d["status"] != "ok" or d.get("error") or any(m.get("quality") != "good" for m in metrics.values()):
            anomaly_count += 1
        elif device_ok:
            ok_devices += 1

    return {
        "ok": True,
        "total_devices": configured_count,
        "live_devices": len(live),
        "anomaly_count": anomaly_count,
        "active_devices": len(live),
        "configured_devices": configured_count,
        "data_quality": round(good_metrics / max(total_metrics, 1) * 100) if configured_count else 0,
        "health": round(ok_devices / configured_count * 100) if configured_count else 0,
    }


# ---------------------------------------------------------------------------
# History — SQL-bucketed time series, one series per requested metric.
# ---------------------------------------------------------------------------

def history_series(
    storage: GatewayInterfacesDataStorage, source_type: str, source_id: str,
    metric_names: list[str], window: str,
) -> dict[str, Any]:
    window_ms = WINDOW_MS.get(window, WINDOW_MS["1h"])
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - window_ms
    bucket_ms = max(1000, window_ms // TARGET_BUCKETS)

    result: dict[str, Any] = {}
    for name in metric_names:
        rows = storage.bucketed_readings(source_type, source_id, name, from_ms, now_ms, bucket_ms)
        if not rows:
            continue
        result[name] = {
            "timestamps": [r["bucket_ts"] for r in rows],
            "avg": [r["avg_v"] for r in rows],
            "min": [r["min_v"] for r in rows],
            "max": [r["max_v"] for r in rows],
            "count": [r["n"] for r in rows],
        }
    return result


# ---------------------------------------------------------------------------
# Rolling stats — 5 min / 1 hr / 24 hr windows, per metric.
# ---------------------------------------------------------------------------

def rolling_stats(
    storage: GatewayInterfacesDataStorage, source_type: str, source_id: str,
    metric_names: list[str], poll_interval_ms: int,
) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    out: dict[str, Any] = {}
    for label, window_ms in STATS_WINDOW_MS.items():
        from_ms = now_ms - window_ms
        expected = max(1, window_ms // max(poll_interval_ms, 50))
        window_stats: dict[str, Any] = {}
        for name in metric_names:
            s = storage.metric_stats(source_type, source_id, name, from_ms, now_ms)
            health_pct = min(100, round(s["sample_count"] / expected * 100)) if s["sample_count"] else None
            window_stats[name] = {**s, "health_pct": health_pct, "computed_at": now_ms}
        out[label] = window_stats
    return out


# ---------------------------------------------------------------------------
# Trends — least-squares slope per minute over the last ~5 min, plus
# time-to-threshold against any matching enabled alert rule.
# ---------------------------------------------------------------------------

def _slope_per_minute(timestamps_ms: list[int], values: list[float]) -> float:
    n = len(values)
    t0 = timestamps_ms[0]
    xs = [(t - t0) / 60_000 for t in timestamps_ms]
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    numer = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    return numer / denom


def compute_trends(
    storage: GatewayInterfacesDataStorage, source_type: str, source_id: str,
    metric_names: list[str], alert_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - TREND_LOOKBACK_MS
    trends: list[dict[str, Any]] = []

    for name in metric_names:
        rows = [
            r for r in storage.readings(source_type=source_type, source_id=source_id, name=name, from_ms=from_ms, to_ms=now_ms, limit=2000)
            if r["value"] is not None
        ]
        if len(rows) < 5:
            continue
        timestamps = [r["ts_ms"] for r in rows]
        values = [r["value"] for r in rows]
        slope = _slope_per_minute(timestamps, values)
        current = values[-1]

        ttt_minutes = None
        ttt_rule = None
        matching = [
            r for r in alert_rules
            if r.get("enabled") and r.get("source") == source_type and r.get("device_id") == source_id and r.get("metric_name") == name
        ]
        if abs(slope) > 1e-6 and matching:
            best: tuple[float, dict[str, Any]] | None = None
            for rule in matching:
                threshold = rule.get("threshold")
                cond = rule.get("condition")
                if threshold is None:
                    continue
                if cond in ("gt", "gte") and slope > 0 and current < threshold:
                    minutes = (threshold - current) / slope
                elif cond in ("lt", "lte") and slope < 0 and current > threshold:
                    minutes = (current - threshold) / abs(slope)
                else:
                    continue
                if minutes > 0 and (best is None or minutes < best[0]):
                    best = (minutes, rule)
            if best:
                ttt_minutes, rule = best
                ttt_rule = {"severity": rule.get("severity", "warning"), "threshold": rule.get("threshold")}

        trends.append({
            "metric_name": name, "slope": slope, "n_samples": len(values),
            "computed_at": now_ms, "ttt_minutes": ttt_minutes, "ttt_rule": ttt_rule,
        })

    return trends


# ---------------------------------------------------------------------------
# CSV export — raw readings, one row per sample.
# ---------------------------------------------------------------------------

def export_csv_rows(
    storage: GatewayInterfacesDataStorage, source_type: str, source_id: str,
    metric_names: list[str], window: str,
) -> list[dict[str, Any]]:
    window_ms = WINDOW_MS.get(window, WINDOW_MS["1h"])
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - window_ms

    rows_out: list[dict[str, Any]] = []
    for name in metric_names:
        for r in storage.readings(source_type=source_type, source_id=source_id, name=name, from_ms=from_ms, to_ms=now_ms, limit=50000):
            rows_out.append({
                "timestamp": _iso(r["ts_ms"]), "source": source_type, "device_id": source_id,
                "metric": name, "value": r["value"], "unit": r["unit"],
                "quality": "good" if r["value"] is not None else "error",
            })
    rows_out.sort(key=lambda r: r["timestamp"])
    return rows_out


# ---------------------------------------------------------------------------
# Alert rules — persisted to a small JSON file so they survive hub restarts.
# ---------------------------------------------------------------------------

def load_alert_rules(path: Path = DEFAULT_ALERT_RULES_PATH) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], 1
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    next_id = max([r.get("id", 0) for r in rules], default=0) + 1
    return rules, next_id


def save_alert_rules(rules: list[dict[str, Any]], path: Path = DEFAULT_ALERT_RULES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"rules": rules}, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Events — real device online/error transitions (from sensor_status_events)
# merged with alert-rule violations (evaluated live, held in memory only).
# Consecutive rows for the same (source, device, event_type) within
# EVENT_GROUP_GAP_MS are collapsed into one row with _count/_first_ts, same
# grouping idea as the Monitor page's anomaly episode dedup.
# ---------------------------------------------------------------------------

class AlertEventStore:
    def __init__(self) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS_MEMORY)

    def evaluate(self, rules: list[dict[str, Any]], configured: list[dict[str, Any]], storage: GatewayInterfacesDataStorage) -> None:
        now_ms = int(time.time() * 1000)
        by_key = {(d["source"], d["device_id"]): d for d in configured}
        for rule in rules:
            if not rule.get("enabled"):
                continue
            device = by_key.get((rule.get("source"), rule.get("device_id")))
            if device is None:
                continue
            latest = storage.latest_readings(rule["source"], rule["device_id"]).get(rule["metric_name"])
            if latest is None or latest["value"] is None:
                continue
            value = latest["value"]
            threshold = rule.get("threshold")
            triggered = {
                "gt": value > threshold, "gte": value >= threshold,
                "lt": value < threshold, "lte": value <= threshold,
                "eq": value == threshold,
            }.get(rule.get("condition"), False)
            if not triggered:
                continue
            self._events.append({
                "severity": rule.get("severity", "warning"),
                "event_type": f"alert:{rule['metric_name']}",
                "device_name": device.get("name"), "device_id": rule["device_id"], "source": rule["source"],
                "message": f"{rule['metric_name']} = {value:g} ({rule.get('condition')} {threshold})",
                "timestamp_ms": now_ms,
            })

    def query(
        self, storage: GatewayInterfacesDataStorage, *, window_ms: int, severity: str,
        source: str, device_id: str, device_lookup: dict[tuple[str, str], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        now_ms = int(time.time() * 1000)
        from_ms = now_ms - window_ms

        rows: list[dict[str, Any]] = []
        for ev in storage.status_events(source_type=source or None, source_id=device_id or None, from_ms=from_ms, to_ms=now_ms, limit=2000):
            device = device_lookup.get((ev["source_type"], ev["source_id"]))
            rows.append({
                "severity": "error" if ev["status"] == "error" else "info",
                "event_type": f"status:{ev['status']}",
                "device_name": device.get("name") if device else ev["source_id"],
                "device_id": ev["source_id"], "source": ev["source_type"],
                "message": ev["error"] or f"Source is now {ev['status']}",
                "timestamp_ms": ev["ts_ms"],
            })

        for ev in self._events:
            if ev["timestamp_ms"] < from_ms:
                continue
            if source and ev["source"] != source:
                continue
            if device_id and ev["device_id"] != device_id:
                continue
            rows.append(dict(ev))

        if severity:
            wanted = {"warning": {"warning", "critical", "error"}, "error": {"error", "critical"}}.get(severity, {severity})
            rows = [r for r in rows if r["severity"] in wanted]

        rows.sort(key=lambda r: r["timestamp_ms"], reverse=True)
        return _group_events(rows)


def _group_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    for row in rows:  # newest first
        for g in grouped:
            if (
                g["source"] == row["source"] and g["device_id"] == row["device_id"]
                and g["event_type"] == row["event_type"]
                and g["_first_ts"] - row["timestamp_ms"] <= EVENT_GROUP_GAP_MS
            ):
                g["_count"] += 1
                g["_first_ts"] = min(g["_first_ts"], row["timestamp_ms"])
                break
        else:
            item = dict(row)
            item["_count"] = 1
            item["_first_ts"] = row["timestamp_ms"]
            grouped.append(item)
    return grouped
