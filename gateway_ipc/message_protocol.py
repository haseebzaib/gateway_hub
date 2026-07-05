from __future__ import annotations

import json
import secrets
import time
from datetime import UTC, datetime
from typing import Any


CONFIG_MESSAGE_KEYS = {
    "rs232": "rs232Config",
    "rs485": "rs485ModbusConfig",
    "modbus_tcp": "tcpModbusConfig",
}


def build_config_message(config_name: str, config_payload: dict[str, Any], *, ack_required: bool = True) -> dict[str, Any]:
    message_key = CONFIG_MESSAGE_KEYS.get(config_name)
    if message_key is None:
        raise ValueError(f"Unsupported config message: {config_name}")

    return {
        "message_id": _message_id("cfg"),
        "message_type": message_key,
        message_key: config_payload,
        "ack_required": ack_required,
        "timestamp": _iso_now(),
    }


def build_combined_config_message(configs: dict[str, dict[str, Any]], *, ack_required: bool = True) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": _message_id("cfg"),
        "message_type": "combinedConfig",
        "ack_required": ack_required,
        "timestamp": _iso_now(),
    }

    for config_name, config_payload in configs.items():
        message_key = CONFIG_MESSAGE_KEYS.get(config_name)
        if message_key is None:
            raise ValueError(f"Unsupported config message: {config_name}")
        message[message_key] = config_payload

    return message


def encode_message(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False)


def decode_inbound_message(payload: bytes | str) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
    message = json.loads(text.strip())
    if not isinstance(message, dict):
        raise ValueError("IPC message must be a JSON object.")
    return message


def inbound_message_type(message: dict[str, Any]) -> str:
    raw_type = message.get("message_type")
    if raw_type == 1:
        return "deviceData"
    if raw_type == 2:
        return "deviceAnamoly"
    if raw_type == 3:
        return "ack"
    if raw_type == 4:
        return "nAck"
    if raw_type == 5:
        return "status"
    if raw_type == 6:
        return "heartBeat"
    return str(raw_type or "unknown")


def normalize_device_data_message(message: dict[str, Any]) -> dict[str, Any]:
    data = message.get("data") if isinstance(message.get("data"), dict) else {}
    timestamp_ms = _number(data.get("timestamp_ms"), int(time.time() * 1000))
    core_count = int(_number(data.get("coreCount"), 0))
    per_core_usage = _number_list(data.get("perCoreUsage"))
    per_core_freq = _number_list(data.get("perCoreFreqMhz"))
    if not core_count:
        core_count = max(len(per_core_usage), len(per_core_freq))

    ram_total_mb = _number(data.get("ramTotalMb"), 0.0)
    ram_used_mb = _number(data.get("ramUsedMb"), 0.0)
    ram_total_bytes = int(ram_total_mb * 1024 * 1024)
    ram_used_bytes = int(ram_used_mb * 1024 * 1024)
    ram_used_percent = (ram_used_mb / ram_total_mb * 100.0) if ram_total_mb > 0 else 0.0

    emmc_total_mb = _number(data.get("emmcTotalMb"), 0.0)
    emmc_used_mb = _number(data.get("emmcUsedMb"), 0.0)
    emmc_used_percent = (emmc_used_mb / emmc_total_mb * 100.0) if emmc_total_mb > 0 else 0.0
    disk_used_percent = _number(data.get("diskUsedPct"), 0.0)

    return {
        "ok": True,
        "source": "gateway_core_ipc",
        "message_id": message.get("message_id"),
        "message_type": "deviceData",
        "timestamp_ms": int(timestamp_ms),
        "received_at": _iso_now(),
        "cpu": {
            "total_percent": _round1(data.get("cpuUsage")),
            "core_count": core_count,
            "per_core": [
                {
                    "core": idx,
                    "usage_percent": _round1(per_core_usage[idx] if idx < len(per_core_usage) else 0),
                    "freq_mhz": int(per_core_freq[idx]) if idx < len(per_core_freq) else 0,
                }
                for idx in range(core_count)
            ],
            "load_average": {
                "1m": _round2(data.get("loadAvg1m")),
                "5m": _round2(data.get("loadAvg5m")),
                "15m": _round2(data.get("loadAvg15m")),
            },
            "throttle_flags": int(_number(data.get("throttleFlags"), 0)),
        },
        "memory": {
            "memory_bytes": {
                "used_percent": _round1(ram_used_percent),
                "used": ram_used_bytes,
                "total": ram_total_bytes,
            },
            "memory_mb": {"used": _round1(ram_used_mb), "total": _round1(ram_total_mb)},
            "swap_mb": {"used": _round1(data.get("swapUsedMb"))},
        },
        "temperature_c": _round1(data.get("cpuTemp")) if _number(data.get("cpuTemp"), 0.0) > 0 else None,
        "filesystem": {
            "used_percent": _round1(disk_used_percent),
            "label": "root filesystem",
        },
        "emmc": {
            "used_percent": _round1(emmc_used_percent),
            "used_mb": _round1(emmc_used_mb),
            "total_mb": _round1(emmc_total_mb),
            "life_used_percent": int(_number(data.get("emmcLifeUsed"), 0)),
        },
        "uptime_sec": int(_number(data.get("uptimeSec"), 0)),
    }


# ── anomaly translation: raw engine output -> plain client language ──────────
#
# The C++ engine speaks in metric IDs (cpu.temp) and detector class names
# (ZScoreDetector). A non-technical operator should never see either. These
# tables turn every event into a friendly label + a plain-English category +
# a one-line headline they can read at a glance.

# metricName -> (friendly label, unit suffix)
_METRIC_LABELS: dict[str, tuple[str, str]] = {
    "cpu.usage": ("CPU Usage", "%"),
    "cpu.temp": ("CPU Temperature", " °C"),
    "cpu.core_count": ("CPU Core Count", ""),
    "cpu.load_1m": ("System Load (1 min)", ""),
    "cpu.load_5m": ("System Load (5 min)", ""),
    "cpu.load_15m": ("System Load (15 min)", ""),
    "cpu.throttle_flags": ("CPU Throttling", ""),
    "memory.ram_used_pct": ("Memory Usage", "%"),
    "memory.ram_used_mb": ("Memory Used", " MB"),
    "memory.ram_total_mb": ("Memory Total", " MB"),
    "memory.swap_used_mb": ("Swap Usage", " MB"),
    "storage.disk_used_pct": ("System Storage", "%"),
    "storage.emmc_used_pct": ("Disk (eMMC) Usage", "%"),
    "storage.emmc_used_mb": ("Disk Used", " MB"),
    "storage.emmc_total_mb": ("Disk Total", " MB"),
    "storage.emmc_life_used_pct": ("Storage Wear", "%"),
    "system.uptime_sec": ("Uptime", " s"),
}

# detectorName (lower-cased) -> plain-English "what kind of problem" category
_DETECTOR_CATEGORY: dict[str, str] = {
    "thresholddetector": "Crossed a safe limit",
    "rangecheckdetector": "Reading looks invalid",
    "deltadetector": "Sudden spike",
    "slopedetector": "Rising quickly",
    "zscoredetector": "Behaving unusually vs normal",
    "timeoutdetector": "Sensor stopped reporting",
    "multiconditiondetector": "Combined warning",
}


def _metric_label(metric_name: str) -> str:
    if metric_name in _METRIC_LABELS:
        return _METRIC_LABELS[metric_name][0]
    # per-core metrics: cpu.core0.usage / cpu.core0.freq_mhz
    if metric_name.startswith("cpu.core"):
        try:
            core = metric_name.split(".")[1].replace("core", "")
            kind = "Frequency" if metric_name.endswith("freq_mhz") else "Usage"
            return f"CPU Core {core} {kind}"
        except (IndexError, ValueError):
            pass
    return metric_name or "Device"


def _metric_unit(metric_name: str) -> str:
    return _METRIC_LABELS.get(metric_name, ("", ""))[1]


def _format_value(value: Any, unit: str) -> str:
    number = _number(value, 0.0)
    text = f"{number:.0f}" if float(number).is_integer() else f"{number:.1f}"
    return f"{text}{unit}"


def normalize_anomaly_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a raw deviceAnamoly IPC message into client-friendly event rows.

    Returns a list ready to hand to MonitorStorage.add_anomaly_events(). Each
    row carries the raw fields the UI may want plus precomputed plain-English
    `category`, `metric_label`, and `headline` fields.
    """
    data = message.get("data") if isinstance(message.get("data"), dict) else {}
    raw_events = data.get("events") if isinstance(data.get("events"), list) else []
    fallback_ts = int(_number(data.get("timestamp_ms"), time.time() * 1000))

    rows: list[dict[str, Any]] = []
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        metric_name = str(event.get("metricName") or "")
        detector = str(event.get("detectorName") or "")
        alarm_name = str(event.get("alarmName") or "")
        severity = str(event.get("severity") or "Info")
        category = _DETECTOR_CATEGORY.get(detector.lower(), "Anomaly detected")
        unit = _metric_unit(metric_name)
        label = alarm_name.replace("_", " ").title() if alarm_name else _metric_label(metric_name)
        headline = _anomaly_headline(event, label, category, unit)

        rows.append(
            {
                "timestamp_ms": int(_number(event.get("timestamp_ms"), fallback_ts)),
                "metric": metric_name or None,
                "detector": detector or None,
                "severity": severity,
                "value": event.get("value"),
                "warning_limit": event.get("warningLimit"),
                "critical_limit": event.get("criticalLimit"),
                "min_value": event.get("minValue"),
                "max_value": event.get("maxValue"),
                "alarm_name": alarm_name or None,
                "category": category,
                "metric_label": label,
                "headline": headline,
                "message": str(event.get("message") or ""),
            }
        )
    return rows


def _anomaly_headline(event: dict[str, Any], label: str, category: str, unit: str) -> str:
    """A single readable sentence, e.g. 'CPU Temperature reached 87 °C (safe limit 85 °C).'"""
    detector = str(event.get("detectorName") or "").lower()
    value_text = _format_value(event.get("value"), unit)

    if detector == "thresholddetector":
        # Reference the limit this severity actually crossed, not always critical.
        severity = str(event.get("severity") or "").lower()
        if severity == "critical" and _number(event.get("criticalLimit"), 0.0):
            limit_text = f"critical limit {_format_value(event.get('criticalLimit'), unit)}"
        elif _number(event.get("warningLimit"), 0.0):
            limit_text = f"warning limit {_format_value(event.get('warningLimit'), unit)}"
        else:
            limit_text = f"limit {_format_value(event.get('criticalLimit'), unit)}"
        return f"{label} reached {value_text}, past the {limit_text}."
    if detector == "rangecheckdetector":
        return (
            f"{label} read {value_text}, outside the expected "
            f"{_format_value(event.get('minValue'), unit)}–{_format_value(event.get('maxValue'), unit)} range."
        )
    if detector == "deltadetector":
        return f"{label} jumped sharply to {value_text}."
    if detector == "slopedetector":
        return f"{label} was climbing quickly."
    if detector == "zscoredetector":
        return f"{label} was unusual compared with its normal pattern."
    if detector == "timeoutdetector":
        return f"{label} stopped reporting."
    if detector == "multiconditiondetector":
        return f"{label}: {event.get('message') or category}."
    return f"{label} was flagged."


def headline_for_stored(row: dict[str, Any], metric: str | None = None) -> str:
    """Rebuild an anomaly's plain-English headline from a stored row.

    Headlines are computed at read time (not frozen at ingest) so wording
    tweaks apply to historical anomalies too, without rewriting the database.
    """
    metric_name = str(metric or row.get("metric") or "")
    label = row.get("metric_label") or _metric_label(metric_name)
    unit = _metric_unit(metric_name)
    event = {
        "detectorName": row.get("detector"),
        "value": row.get("value"),
        "criticalLimit": row.get("critical_limit"),
        "warningLimit": row.get("warning_limit"),
        "minValue": row.get("min_value"),
        "maxValue": row.get("max_value"),
        "severity": row.get("severity"),
        "message": row.get("message"),
    }
    return _anomaly_headline(event, label, str(row.get("category") or ""), unit)


def chart_metric_values(metrics: dict[str, Any]) -> dict[str, float]:
    """Pull the charted metrics out of normalized device data, keyed by the
    C++ metricName strings so stored series line up with anomaly overlays."""
    cpu = metrics.get("cpu", {}) if isinstance(metrics.get("cpu"), dict) else {}
    memory = metrics.get("memory", {}) if isinstance(metrics.get("memory"), dict) else {}
    filesystem = metrics.get("filesystem", {}) if isinstance(metrics.get("filesystem"), dict) else {}
    emmc = metrics.get("emmc", {}) if isinstance(metrics.get("emmc"), dict) else {}

    values: dict[str, float] = {
        "cpu.usage": _number(cpu.get("total_percent"), 0.0),
        "memory.ram_used_pct": _number(memory.get("memory_bytes", {}).get("used_percent"), 0.0),
        "storage.disk_used_pct": _number(filesystem.get("used_percent"), 0.0),
        "storage.emmc_used_pct": _number(emmc.get("used_percent"), 0.0),
        "cpu.load_1m": _number(cpu.get("load_average", {}).get("1m"), 0.0),
    }
    # temperature is None when the sensor is unreadable; skip rather than store 0.
    temperature = metrics.get("temperature_c")
    if temperature is not None:
        values["cpu.temp"] = _number(temperature, 0.0)
    return values


def device_metric_history_sample(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp_ms": metrics.get("timestamp_ms"),
        "cpu_total_percent": metrics.get("cpu", {}).get("total_percent", 0),
        "memory_used_percent": metrics.get("memory", {}).get("memory_bytes", {}).get("used_percent", 0),
        "temperature_c": metrics.get("temperature_c") or 0,
        "disk_used_percent": metrics.get("filesystem", {}).get("used_percent", 0),
        "emmc_used_percent": metrics.get("emmc", {}).get("used_percent", 0),
        "load_avg_1m": metrics.get("cpu", {}).get("load_average", {}).get("1m", 0),
    }


def _message_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}-{secrets.token_hex(4)}"


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _number_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [_number(item, 0.0) for item in value]


def _round1(value: Any) -> float:
    return round(_number(value, 0.0), 1)


def _round2(value: Any) -> float:
    return round(_number(value, 0.0), 2)
