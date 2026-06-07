from __future__ import annotations

import os
from typing import Any

import httpx


class EngineClient:
    def __init__(self, base_url: str | None = None, timeout: float = 2.0) -> None:
        self._base_url = base_url or os.environ.get("GATEWAY_ENGINE_URL", "http://127.0.0.1:8080")
        self._timeout = timeout

    async def get_json(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(path)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"data": data}

    async def health(self) -> dict[str, Any]:
        try:
            return await self.get_json("/health")
        except Exception as exc:
            return {"ok": False, "state": "unreachable", "error": str(exc)}

