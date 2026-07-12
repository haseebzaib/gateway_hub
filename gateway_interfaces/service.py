from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import default_config, normalize_config
from .storage import GatewayInterfacesStorage


class GatewayInterfacesService:
    def __init__(self, storage: GatewayInterfacesStorage | None = None) -> None:
        self.storage = storage or GatewayInterfacesStorage()
        self._config = default_config()

    def load(self) -> dict[str, Any]:
        payload = self.storage.load()
        if payload is None:
            payload = self._load_legacy_files()
            self._config = normalize_config(payload or self._config)
            if payload is not None:
                self.storage.save(self._config)
        else:
            self._config = normalize_config(payload)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._config)

    def section(self, name: str) -> dict[str, Any]:
        if name not in {"rs232", "rs485", "modbus_tcp"}:
            raise ValueError(f"Unsupported gateway interface section: {name}")
        section = deepcopy(self._config[name])
        if name in {"rs232", "rs485"}:
            return {"version": self._config["version"], name: section}
        return {"version": self._config["version"], **section}

    def update_section(self, name: str, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, object]]:
        candidate = self.snapshot()
        if name in {"rs232", "rs485"}:
            candidate[name] = payload.get(name, {})
        elif name == "modbus_tcp":
            candidate[name] = {
                "max_connections": payload.get("max_connections", 10),
                "connections": payload.get("connections", []),
            }
        else:
            raise ValueError(f"Unsupported gateway interface section: {name}")
        candidate["version"] = payload.get("version", candidate["version"])
        self._config = normalize_config(candidate)
        storage_result = self.storage.save(self._config)
        return self.section(name), storage_result

    def _load_legacy_files(self) -> dict[str, Any] | None:
        directory = Path(os.environ.get("GATEWAY_SENSOR_CONFIG_DIR", "/opt/metacrust/sensorconfigs"))
        paths = {
            "rs232": directory / "rs232.json",
            "rs485": directory / "rs485.json",
            "modbus_tcp": directory / "modbus_tcp.json",
        }
        if not any(path.exists() for path in paths.values()):
            return None
        merged = default_config()
        for name, path in paths.items():
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            if name in {"rs232", "rs485"}:
                merged[name] = payload.get(name, merged[name])
            else:
                merged[name] = {
                    "max_connections": payload.get("max_connections", 10),
                    "connections": payload.get("connections", []),
                }
        return merged
