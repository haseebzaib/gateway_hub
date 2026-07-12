from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("/opt/metacrust/config/gateway_interfaces/config.json")


class GatewayInterfacesStorage:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or os.environ.get("GATEWAY_INTERFACES_CONFIG_PATH") or DEFAULT_CONFIG_PATH)

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid gateway interfaces config in {self.path}")
        return payload

    def save(self, payload: dict[str, Any]) -> dict[str, object]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        return {"saved": True, "path": str(self.path)}
