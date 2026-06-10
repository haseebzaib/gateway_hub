from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from .client import GatewayCoreTcpClient
from .config import IpcClientConfig

@dataclass
class IpcStatus:
    enabled: bool
    connected: bool = False
    state: str = "stopped"
    host: str = "127.0.0.1"
    port: int = 8765
    framing: str = "newline"
    last_connected_at: str | None = None
    last_disconnected_at: str | None = None
    last_error: str | None = None
    last_rx_text: str | None = None
    rx_count: int = 0
    tx_count: int = 0
    heartbeat_count: int = 0


class GatewayCoreIpcTask:
    def __init__(self, config: IpcClientConfig | None = None) -> None:
        self.config = config or IpcClientConfig.from_env()
        self.client = GatewayCoreTcpClient(self.config)
        self.status = IpcStatus(
            enabled=self.config.enabled,
            host=self.config.host,
            port=self.config.port,
            framing=self.config.framing,
        )
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if not self.config.enabled:
            self.status.state = "disabled"
            _console("disabled")
            return
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self.status.state = "starting"
            _console(f"starting client {self.config.host}:{self.config.port} framing={self.config.framing}")
            self._task = asyncio.create_task(self._run(), name="gateway-core-ipc")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.client.close()
        self.status.connected = False
        self.status.state = "stopped"

    async def send_text(self, message: str) -> None:
        await self.client.send_text(message)
        self.status.tx_count += 1
        _console(f"TX ipc_payload={message}")

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.status.enabled,
            "connected": self.status.connected,
            "state": self.status.state,
            "host": self.status.host,
            "port": self.status.port,
            "framing": self.status.framing,
            "last_connected_at": self.status.last_connected_at,
            "last_disconnected_at": self.status.last_disconnected_at,
            "last_error": self.status.last_error,
            "last_rx_text": self.status.last_rx_text,
            "rx_count": self.status.rx_count,
            "tx_count": self.status.tx_count,
            "heartbeat_count": self.status.heartbeat_count,
        }

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.status.state = "connecting"
                await self.client.connect()
                self.status.connected = True
                self.status.state = "connected"
                self.status.last_error = None
                self.status.last_connected_at = _utc_now()
                _console(f"connected {self.config.host}:{self.config.port}")

                async for payload in self.client.read_messages():
                    self.status.rx_count += 1
                    self.status.last_rx_text = _decode_preview(payload)
                    _console(f"RX {self.status.last_rx_text}")
                    if self._stop_event.is_set():
                        break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.last_error = str(exc)
                self.status.state = "reconnecting"
                _console(f"unavailable: {exc}")
            finally:
                await self.client.close()
                if self.status.connected:
                    self.status.last_disconnected_at = _utc_now()
                    _console("disconnected")
                self.status.connected = False

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.config.reconnect_delay_s)
            except TimeoutError:
                continue

def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _console(message: str) -> None:
    print(f"[gateway-ipc] {message}", flush=True)


def _decode_preview(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace").strip()
    return text[:1000]
