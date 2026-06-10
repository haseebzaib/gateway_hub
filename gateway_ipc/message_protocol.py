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


def _message_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}-{secrets.token_hex(4)}"


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
