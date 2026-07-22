from __future__ import annotations

import json
import os
import time
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

EVENT_GROUP_GAP_MS = 60_000


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
    metric_names: list[str], detection_config: dict[str, Any],
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
        threshold_cfg = get_metric_detection_config(detection_config, source_type, source_id, name).get("threshold")
        if abs(slope) > 1e-6 and threshold_cfg and threshold_cfg.get("enabled"):
            trigger_above = bool(threshold_cfg.get("trigger_above", True))
            candidates = [
                ("critical", threshold_cfg.get("critical_limit")),
                ("warning", threshold_cfg.get("warning_limit")),
            ]
            best: tuple[float, str, float] | None = None
            for severity, limit in candidates:
                if limit is None:
                    continue
                limit = float(limit)
                if trigger_above and slope > 0 and current < limit:
                    minutes = (limit - current) / slope
                elif not trigger_above and slope < 0 and current > limit:
                    minutes = (current - limit) / abs(slope)
                else:
                    continue
                if minutes > 0 and (best is None or minutes < best[0]):
                    best = (minutes, severity, limit)
            if best:
                ttt_minutes, severity, limit = best
                ttt_rule = {"severity": severity, "threshold": limit}

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
# Events — real device online/error transitions (sensor_status_events) merged
# with real detector-fired anomalies (sensor_anomaly_events, from the C++
# engine — see detection config below). Consecutive rows for the same
# (source, device, event_type) within EVENT_GROUP_GAP_MS are collapsed into
# one row with _count/_first_ts, same grouping idea as the Monitor page's
# anomaly episode dedup (the episode coalescing in gateway_ipc/task.py has
# already thinned repeats before they reach the DB; this just re-groups for
# display, e.g. after a window/filter change).
# ---------------------------------------------------------------------------

def query_events(
    storage: GatewayInterfacesDataStorage, *, window_ms: int, severity: str,
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

    for ev in storage.sensor_anomaly_events(source_type=source or None, source_id=device_id or None, from_ms=from_ms, to_ms=now_ms, limit=2000):
        device = device_lookup.get((ev["source_type"], ev["source_id"]))
        rows.append({
            "severity": str(ev.get("severity") or "info").lower(),
            "event_type": f"anomaly:{ev.get('category') or 'detected'}",
            "device_name": device.get("name") if device else ev["source_id"],
            "device_id": ev["source_id"], "source": ev["source_type"],
            "message": ev.get("headline") or ev.get("message") or "Anomaly detected",
            "timestamp_ms": ev["ts_ms"],
        })

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


# ---------------------------------------------------------------------------
# Detection config — the friendly, per-metric settings the Insights Sensors
# tab lets a user turn on, persisted to JSON (survives hub restarts) and
# translated into the exact sensorAnomalyConfig payload gateway_core expects
# (see gateway_core/include/gateway/core/sensor_anomaly_config.hpp). This is
# what actually configures the real C++ detectors — it supersedes the old
# hub-side gt/lt-only alert-rules system.
# ---------------------------------------------------------------------------

DEFAULT_DETECTION_CONFIG_PATH = Path(
    os.environ.get("METACRUST_DETECTION_CONFIG_PATH", "/opt/metacrust/config/gateway_insights/detection_config.json")
)

# z-score is exposed to non-technical users as a sensitivity slider rather
# than raw warmup/min_std_dev/min_abs_delta params — "high" flags more (smaller
# real-unit gap required before it's considered unusual), "low" flags less.
Z_SENSITIVITY_PRESETS: dict[str, dict[str, float]] = {
    "low": {"warning_z": 3.5, "critical_z": 6.0, "abs_delta_multiplier": 2.0},
    "medium": {"warning_z": 3.0, "critical_z": 5.0, "abs_delta_multiplier": 1.0},
    "high": {"warning_z": 2.5, "critical_z": 4.0, "abs_delta_multiplier": 0.5},
}


def load_detection_config(path: Path = DEFAULT_DETECTION_CONFIG_PATH) -> dict[str, Any]:
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            return {
                "metrics": payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {},
                "multi_condition": payload.get("multi_condition", []) if isinstance(payload.get("multi_condition"), list) else [],
            }
    return {"metrics": {}, "multi_condition": []}


def save_detection_config(config: dict[str, Any], path: Path = DEFAULT_DETECTION_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    tmp.replace(path)


def _metric_key(source: str, device_id: str, metric_name: str) -> str:
    return f"{source}|{device_id}|{metric_name}"


def get_metric_detection_config(config: dict[str, Any], source: str, device_id: str, metric_name: str) -> dict[str, Any]:
    return config.get("metrics", {}).get(_metric_key(source, device_id, metric_name), {})


def set_metric_detection_config(config: dict[str, Any], source: str, device_id: str, metric_name: str, friendly: dict[str, Any]) -> None:
    config.setdefault("metrics", {})[_metric_key(source, device_id, metric_name)] = friendly


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _translate_zscore(friendly: dict[str, Any], metric_name: str, stats: dict[str, Any] | None) -> dict[str, Any]:
    if friendly.get("advanced"):
        return {
            "metric_name": metric_name,
            "warning_z": _num(friendly.get("warning_z"), 3.0),
            "critical_z": _num(friendly.get("critical_z"), 5.0),
            "warmup_samples": int(friendly.get("warmup_samples", 30)),
            "min_std_dev": _num(friendly.get("min_std_dev"), 0.0),
            "min_abs_delta": _num(friendly.get("min_abs_delta"), 0.0),
            "message": friendly.get("message", ""),
        }

    preset = Z_SENSITIVITY_PRESETS.get(friendly.get("sensitivity", "medium"), Z_SENSITIVITY_PRESETS["medium"])
    stddev = _num((stats or {}).get("stddev"), 0.0)
    return {
        "metric_name": metric_name,
        "warning_z": preset["warning_z"],
        "critical_z": preset["critical_z"],
        "warmup_samples": 30,
        "min_std_dev": max(stddev * 0.05, 1e-6),
        "min_abs_delta": stddev * preset["abs_delta_multiplier"],
        "message": friendly.get("message", ""),
    }


def build_sensor_anomaly_payload(
    config: dict[str, Any], source_type: str, source_id: str,
    expected_metrics: list[dict[str, Any]], poll_interval_ms: int,
    stats_by_metric: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the full sensorAnomalyConfig payload for one sensor from its
    friendly per-metric settings — always the FULL set (not a diff), since
    gateway_core's apply_anomaly_rules() replaces this connection's rules
    wholesale each time, same as tcpModbusConfig already does for connections."""
    payload: dict[str, Any] = {
        "source_type": source_type, "source_id": source_id,
        "threshold": [], "range": [], "delta": [], "slope": [], "z_score": [], "timeout": [], "multi_condition": [],
    }

    for metric in expected_metrics:
        name = metric["name"]
        friendly = get_metric_detection_config(config, source_type, source_id, name)
        if not friendly:
            continue

        threshold = friendly.get("threshold")
        if threshold and threshold.get("enabled"):
            payload["threshold"].append({
                "metric_name": name,
                "warning_limit": _num(threshold.get("warning_limit"), 0.0),
                "critical_limit": _num(threshold.get("critical_limit"), 0.0),
                "trigger_above": bool(threshold.get("trigger_above", True)),
                "message": threshold.get("message", ""),
            })

        range_cfg = friendly.get("range")
        if range_cfg and range_cfg.get("enabled"):
            payload["range"].append({
                "metric_name": name,
                "min_value": _num(range_cfg.get("min_value"), 0.0),
                "max_value": _num(range_cfg.get("max_value"), 0.0),
                "severity": range_cfg.get("severity", "warning"),
                "message": range_cfg.get("message", ""),
            })

        delta = friendly.get("delta")
        if delta and delta.get("enabled"):
            payload["delta"].append({
                "metric_name": name,
                "warning_delta": _num(delta.get("warning_delta"), 0.0),
                "critical_delta": _num(delta.get("critical_delta"), 0.0),
                "trigger_positive": bool(delta.get("trigger_positive", True)),
                "max_sample_gap_ms": int(delta.get("max_sample_gap_ms", max(30000, poll_interval_ms * 10))),
                "message": delta.get("message", ""),
            })

        slope = friendly.get("slope")
        if slope and slope.get("enabled"):
            payload["slope"].append({
                "metric_name": name,
                "warning_slope_per_min": _num(slope.get("warning_slope_per_min"), 0.0),
                "critical_slope_per_min": _num(slope.get("critical_slope_per_min"), 0.0),
                "min_elapsed_ms": int(slope.get("min_elapsed_ms", max(10000, poll_interval_ms * 5))),
                "min_samples": int(slope.get("min_samples", 5)),
                "trigger_positive": bool(slope.get("trigger_positive", True)),
                "window_ms": int(slope.get("window_ms", 300000)),
                "max_sample_gap_ms": int(slope.get("max_sample_gap_ms", max(30000, poll_interval_ms * 10))),
                "message": slope.get("message", ""),
            })

        z_score = friendly.get("z_score")
        if z_score and z_score.get("enabled"):
            payload["z_score"].append(_translate_zscore(z_score, name, stats_by_metric.get(name)))

        timeout = friendly.get("timeout")
        if timeout and timeout.get("enabled"):
            payload["timeout"].append({
                "metric_name": name,
                "timeout_ms": int(timeout.get("timeout_ms", max(10000, poll_interval_ms * 8))),
                "severity": timeout.get("severity", "warning"),
                "message": timeout.get("message", ""),
            })

    for rule in config.get("multi_condition", []):
        if rule.get("source_type") == source_type and rule.get("source_id") == source_id and rule.get("enabled", True):
            payload["multi_condition"].append({
                "alarm_name": rule.get("alarm_name", ""),
                "conditions": rule.get("conditions", []),
                "logic": rule.get("logic", "all"),
                "severity": rule.get("severity", "warning"),
                "message": rule.get("message", ""),
            })

    return payload
