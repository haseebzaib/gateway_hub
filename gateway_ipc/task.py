from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .client import GatewayCoreTcpClient
from .config import IpcClientConfig
from .message_protocol import (
    chart_metric_values,
    decode_inbound_message,
    device_metric_history_sample,
    inbound_message_type,
    normalize_anomaly_message,
    normalize_device_data_message,
)
from .monitor_storage import MonitorStorage

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
    def __init__(self, config: IpcClientConfig | None = None, storage: MonitorStorage | None = None) -> None:
        self.config = config or IpcClientConfig.from_env()
        self.client = GatewayCoreTcpClient(self.config)
        self.status = IpcStatus(
            enabled=self.config.enabled,
            host=self.config.host,
            port=self.config.port,
            framing=self.config.framing,
        )
        self.storage = storage or MonitorStorage()
        self._latest_device_metrics: dict[str, Any] | None = None
        self._device_metric_history: deque[dict[str, Any]] = deque(maxlen=600)
        self._anomaly_count = 0
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        try:
            self.storage.open()
        except Exception as exc:  # storage must never take down the IPC task
            _console(f"monitor storage unavailable: {exc}")
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
        try:
            self.storage.close()
        except Exception as exc:
            _console(f"monitor storage close failed: {exc}")

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
            "latest_device_metrics_at": self._latest_device_metrics.get("received_at") if self._latest_device_metrics else None,
            "anomaly_count": self._anomaly_count,
        }

    def latest_device_metrics(self) -> dict[str, Any] | None:
        return dict(self._latest_device_metrics) if self._latest_device_metrics else None

    def device_metric_history(self) -> list[dict[str, Any]]:
        return list(self._device_metric_history)

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
                    self._handle_rx_payload(payload)
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

    def _handle_rx_payload(self, payload: bytes) -> None:
        try:
            message = decode_inbound_message(payload)
            message_type = inbound_message_type(message)
            if message_type == "deviceData":
                metrics = normalize_device_data_message(message)
                self._latest_device_metrics = metrics
                self._device_metric_history.append(device_metric_history_sample(metrics))
                self._store_metric_sample(metrics)
            elif message_type == "deviceAnamoly":
                self._store_anomaly_events(message)
            elif message_type == "heartBeat":
                self.status.heartbeat_count += 1
        except json.JSONDecodeError as exc:
            self.status.last_error = f"invalid IPC JSON: {exc}"
        except Exception as exc:
            self.status.last_error = f"IPC message parse failed: {exc}"

    def _store_metric_sample(self, metrics: dict[str, Any]) -> None:
        try:
            timestamp_ms = int(metrics.get("timestamp_ms") or 0)
            self.storage.add_metric_sample(chart_metric_values(metrics), timestamp_ms)
        except Exception as exc:
            self.status.last_error = f"metric store failed: {exc}"

    def _store_anomaly_events(self, message: dict[str, Any]) -> None:
        try:
            rows = normalize_anomaly_message(message)
            if rows:
                self.storage.add_anomaly_events(rows)
                self._anomaly_count += len(rows)
        except Exception as exc:
            self.status.last_error = f"anomaly store failed: {exc}"

def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _console(message: str) -> None:
    print(f"[gateway-ipc] {message}", flush=True)


def _decode_preview(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace").strip()
    return text[:1000]
