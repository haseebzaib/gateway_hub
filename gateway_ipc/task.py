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

# Two anomalies of the same (metric, detector) within this gap are treated as
# one ongoing episode; a longer quiet gap starts a fresh episode.
EPISODE_GAP_MS = 20_000
_SEVERITY_RANK = {"Info": 1, "Warning": 2, "Critical": 3}


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
        # (metric, detector) -> {"last_ts": ms, "rank": severity} for episode dedup
        self._anomaly_episodes: dict[tuple[Any, Any], dict[str, Any]] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._pending_acks: dict[str, asyncio.Future[dict[str, Any]]] = {}

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

    async def send_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Send one protocol message and, when requested, await its ACK/NACK."""
        message_id = str(message.get("message_id") or "")
        if not message.get("ack_required"):
            await self.send_text(json.dumps(message, separators=(",", ":"), ensure_ascii=False))
            return None
        if not message_id:
            raise ValueError("ACK-required IPC messages need a message_id.")
        if message_id in self._pending_acks:
            raise ValueError(f"IPC message is already awaiting ACK: {message_id}")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_acks[message_id] = future
        encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        try:
            attempts = max(1, self.config.ack_retries + 1)
            for attempt in range(attempts):
                await self.send_text(encoded)
                try:
                    reply = await asyncio.wait_for(asyncio.shield(future), timeout=self.config.ack_timeout_s)
                except TimeoutError:
                    if attempt + 1 == attempts:
                        raise TimeoutError(f"No ACK from gateway core for {message_id} after {attempts} attempts")
                    continue
                if inbound_message_type(reply) == "nAck":
                    raise RuntimeError(str(reply.get("error") or f"Gateway core rejected {message_id}"))
                return reply
        finally:
            self._pending_acks.pop(message_id, None)
            if not future.done():
                future.cancel()
        return None

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
            elif message_type in {"ack", "nAck"}:
                correlation_id = str(message.get("correlation_id") or "")
                future = self._pending_acks.get(correlation_id)
                if future is not None and not future.done():
                    future.set_result(message)
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
            rows = self._coalesce_episodes(normalize_anomaly_message(message))
            if rows:
                self.storage.add_anomaly_events(rows)
                self._anomaly_count += len(rows)
        except Exception as exc:
            self.status.last_error = f"anomaly store failed: {exc}"

    def _coalesce_episodes(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse a still-true condition into one alert per episode.

        The engine re-emits the same finding every second while a condition
        holds (CPU stuck high, a slope window still holding an old rise). We keep
        only the leading edge of each episode — plus one more if it escalates to
        a higher severity — and start a fresh episode only after the condition
        has been quiet for EPISODE_GAP_MS. This is edge-triggered alerting.
        """
        kept: list[dict[str, Any]] = []
        for row in rows:
            key = (row.get("metric"), row.get("detector"))
            ts = int(row.get("timestamp_ms") or 0)
            rank = _SEVERITY_RANK.get(row.get("severity"), 1)
            episode = self._anomaly_episodes.get(key)

            if episode is None or ts - episode["last_ts"] > EPISODE_GAP_MS:
                kept.append(row)                       # new episode (leading edge)
                self._anomaly_episodes[key] = {"last_ts": ts, "rank": rank}
                continue

            if rank > episode["rank"]:
                kept.append(row)                       # escalation within episode
            episode["last_ts"] = ts                    # extend the live episode
            episode["rank"] = max(episode["rank"], rank)
        return kept

def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _console(message: str) -> None:
    print(f"[gateway-ipc] {message}", flush=True)


def _decode_preview(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace").strip()
    return text[:1000]
