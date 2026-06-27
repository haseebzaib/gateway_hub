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
