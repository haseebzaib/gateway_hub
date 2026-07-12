from __future__ import annotations

from copy import deepcopy
from typing import Any


def _default_dustrak() -> dict[str, Any]:
    return {
        "polling": {
            "read_identity_on_init": True,
            "poll_status": True,
            "auto_start_measurement": False,
            "poll_measurements": True,
            "poll_measurement_stats": False,
            "poll_fault_messages": False,
            "poll_alarm_messages": False,
            "poll_log_info": False,
        },
        "driver": {"update_ram_after_write": True},
        "alarms": {
            channel: {
                "alarm1_state": "off",
                "alarm1_mg_per_m3": 0.0,
                "stel_alarm1_enabled": False,
                "alarm2_state": "off",
                "alarm2_mg_per_m3": 0.0,
            }
            for channel in ("pm1", "pm25", "pm4", "pm10", "total")
        },
        "analog_output": {
            "state": "off",
            "channel": None,
            "min_mg_per_m3": 0.0,
            "max_mg_per_m3": 1.0,
        },
    }


def _default_serial() -> dict[str, Any]:
    return {"baud_rate": 9600, "data_bits": 8, "parity": "none", "stop_bits": 1}


def _default_rs232_port() -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": "sensor",
        "serial": _default_serial(),
        "sensor": "dustrak",
        "dustrak": _default_dustrak(),
        "sniffer": {
            "display_format": "ascii_hex",
            "framing": "line",
            "line_delimiter": "crlf",
            "fixed_frame_bytes": 32,
            "idle_gap_ms": 100,
            "timestamp": True,
            "max_live_buffer_bytes": 1048576,
            "capture": {
                "enabled": False,
                "format": "jsonl",
                "retention_days": 7,
                "max_size_mb": 100,
            },
        },
    }


def _default_rtu_port() -> dict[str, Any]:
    return {
        "enabled": False,
        "serial": _default_serial(),
        "modbus_rtu": {"slave_address": 1, "poll_interval_ms": 1000, "registers": []},
    }


def default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "rs232": {"port_0": _default_rs232_port(), "port_1": _default_rs232_port()},
        "rs485": {"port_2": _default_rtu_port(), "port_3": _default_rtu_port()},
        "modbus_tcp": {"max_connections": 10, "connections": []},
    }


def normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Gateway interfaces configuration must be a JSON object.")
    config = default_config()
    config["version"] = _integer(payload.get("version"), 1, 1, 1)

    for port_name in ("port_0", "port_1"):
        raw = _mapping(_mapping(payload.get("rs232")).get(port_name))
        config["rs232"][port_name] = _normalize_rs232_port(raw, config["rs232"][port_name])
    for port_name in ("port_2", "port_3"):
        raw = _mapping(_mapping(payload.get("rs485")).get(port_name))
        config["rs485"][port_name] = _normalize_rtu_port(raw, config["rs485"][port_name])

    tcp = _mapping(payload.get("modbus_tcp"))
    connections = tcp.get("connections") if isinstance(tcp.get("connections"), list) else []
    config["modbus_tcp"] = {
        "max_connections": 10,
        "connections": [_normalize_tcp_connection(item, index) for index, item in enumerate(connections[:10]) if isinstance(item, dict)],
    }
    return config


def _normalize_rs232_port(raw: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(default)
    result["enabled"] = bool(raw.get("enabled", result["enabled"]))
    result["mode"] = _choice(raw.get("mode"), {"sensor", "sniffer"}, "sensor")
    result["serial"] = _normalize_serial(_mapping(raw.get("serial")), result["serial"])
    result["sensor"] = str(raw.get("sensor") or "dustrak")
    _merge_known(result["dustrak"], _mapping(raw.get("dustrak")))
    _merge_known(result["sniffer"], _mapping(raw.get("sniffer")))

    sniffer = result["sniffer"]
    sniffer["display_format"] = _choice(sniffer.get("display_format"), {"ascii", "hex", "ascii_hex"}, "ascii_hex")
    sniffer["framing"] = _choice(sniffer.get("framing"), {"raw", "line", "fixed_length", "idle_gap"}, "line")
    sniffer["line_delimiter"] = _choice(sniffer.get("line_delimiter"), {"cr", "lf", "crlf"}, "crlf")
    sniffer["fixed_frame_bytes"] = _integer(sniffer.get("fixed_frame_bytes"), 32, 1, 65536)
    sniffer["idle_gap_ms"] = _integer(sniffer.get("idle_gap_ms"), 100, 1, 60000)
    sniffer["max_live_buffer_bytes"] = _integer(sniffer.get("max_live_buffer_bytes"), 1048576, 4096, 16777216)
    sniffer["timestamp"] = bool(sniffer.get("timestamp", True))
    capture = _mapping(sniffer.get("capture"))
    sniffer["capture"] = {
        "enabled": bool(capture.get("enabled", False)),
        "format": "jsonl",
        "retention_days": _integer(capture.get("retention_days"), 7, 1, 365),
        "max_size_mb": _integer(capture.get("max_size_mb"), 100, 1, 10240),
    }
    return result


def _normalize_rtu_port(raw: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(default)
    result["enabled"] = bool(raw.get("enabled", False))
    result["serial"] = _normalize_serial(_mapping(raw.get("serial")), result["serial"])
    rtu = _mapping(raw.get("modbus_rtu"))
    result["modbus_rtu"] = {
        "slave_address": _integer(rtu.get("slave_address"), 1, 1, 247),
        "poll_interval_ms": _integer(rtu.get("poll_interval_ms"), 1000, 50, 3600000),
        "registers": _normalize_registers(rtu.get("registers")),
    }
    return result


def _normalize_tcp_connection(raw: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": str(raw.get("id") or f"conn_{index + 1}"),
        "name": str(raw.get("name") or "Unnamed Device"),
        "enabled": bool(raw.get("enabled", False)),
        "interface": str(raw.get("interface") or "eth0"),
        "ip": str(raw.get("ip") or ""),
        "port": _integer(raw.get("port"), 502, 1, 65535),
        "unit_id": _integer(raw.get("unit_id"), 1, 1, 247),
        "poll_interval_ms": _integer(raw.get("poll_interval_ms"), 1000, 50, 3600000),
        "registers": _normalize_registers(raw.get("registers")),
    }


def _normalize_registers(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        result.append({
            "name": str(raw.get("name") or ""),
            "register_type": _choice(raw.get("register_type"), {"coil", "discrete_input", "input_register", "holding_register"}, "holding_register"),
            "address": _integer(raw.get("address"), 0, 0, 65535),
            "data_type": _choice(raw.get("data_type"), {"uint16", "int16", "uint32", "int32", "float32", "bool"}, "uint16"),
            "word_order": _choice(raw.get("word_order"), {"big", "little"}, "big"),
            "scale": _number(raw.get("scale"), 1.0),
            "unit": str(raw.get("unit") or ""),
        })
    return result


def _normalize_serial(raw: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
    return {
        "baud_rate": _integer(raw.get("baud_rate"), default["baud_rate"], 50, 4000000),
        "data_bits": _integer(raw.get("data_bits"), default["data_bits"], 5, 8),
        "parity": _choice(raw.get("parity"), {"none", "even", "odd"}, "none"),
        "stop_bits": _integer(raw.get("stop_bits"), default["stop_bits"], 1, 2),
    }


def _merge_known(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if key not in target:
            continue
        if isinstance(target[key], dict) and isinstance(value, dict):
            _merge_known(target[key], value)
        else:
            target[key] = value


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _choice(value: Any, choices: set[str], default: str) -> str:
    text = str(value or "")
    return text if text in choices else default


def _integer(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
