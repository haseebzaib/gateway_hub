from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import socket
import ssl
import subprocess
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .storage import ANOMALY_EVENT_TYPES, EdgeServerStorage


LOGGER = logging.getLogger("edge_server")
LOGGER.setLevel(logging.INFO)
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s edge_server %(message)s"))
    LOGGER.addHandler(_handler)
LOGGER.propagate = False


@dataclass
class ListenerState:
    name: str
    enabled: bool = False
    state: str = "stopped"
    bind_host: str = ""
    bind_hosts: list[str] | None = None
    port: int = 0
    error: str | None = None


class EdgeServerTask:
    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._servers: dict[str, asyncio.AbstractServer] = {}
        self._server_keys: dict[str, tuple[str, str, int, str, bool]] = {}
        self._failed_keys: dict[str, tuple[str, str, int, str, bool]] = {}
        self._listeners: dict[str, ListenerState] = {
            name: ListenerState(name=name) for name in ("http", "https", "mqtt", "mqtts")
        }
        self._devices: dict[str, dict[str, Any]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._records: deque[dict[str, Any]] = deque(maxlen=5000)
        self._buffer = {"pending": 0, "processed": 0, "forwarded": 0, "dropped": 0}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._interface_state: dict[str, Any] = {}
        self._interface_signature = ""
        self._last_config_generation = 0
        self._storage = EdgeServerStorage()
        self._storage_enabled = True
        self._mqtt_sessions: dict[str, dict[str, Any]] = {}
        self._mqtt_client_devices: dict[str, set[str]] = {}
        self._mqtt_connect_history: dict[str, deque[float]] = {}

    def start(self, config: dict[str, Any]) -> None:
        self._config = deepcopy(config)
        if self._storage_enabled:
            try:
                self._storage.open()
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_open_failed error=%s", exc)
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run(), name="gateway-edge-server")
            LOGGER.info(
                "task_start http_endpoints=%d mqtt_topics=%d",
                len(self._config.get("http_endpoints") or []),
                len(self._config.get("mqtt_topics") or []),
            )

    async def stop(self) -> None:
        LOGGER.info("task_stop_requested")
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._stop_all()
        self._storage.close()
        LOGGER.info("task_stopped")

    async def apply_config(self, config: dict[str, Any]) -> None:
        async with self._lock:
            self._config = deepcopy(config)
            self._last_config_generation += 1
            self._failed_keys.clear()
            listeners = self._config.get("listeners") or {}
            enabled = [name for name in ("http", "https", "mqtt", "mqtts") if (listeners.get(name) or {}).get("enabled")]
            LOGGER.info(
                "config_apply generation=%d enabled=%s http_endpoints=%d mqtt_topics=%d",
                self._last_config_generation,
                ",".join(enabled) if enabled else "none",
                len(self._config.get("http_endpoints") or []),
                len(self._config.get("mqtt_topics") or []),
            )
            await self._reconcile_locked()

    async def reload_tls(self) -> None:
        async with self._lock:
            LOGGER.info("tls_reload_requested")
            self._failed_keys.clear()
            for name in ("https", "mqtts"):
                for server_id in [key for key in self._servers if key.startswith(f"{name}@")]:
                    await self._stop_server(server_id)
            await self._reconcile_locked()

    def snapshot(self) -> dict[str, Any]:
        enabled_services = [
            name.upper()
            for name, state in self._listeners.items()
            if state.enabled and state.state == "running"
        ]
        errors = [state.error for state in self._listeners.values() if state.error]
        audit_events = list(self._events)[-20:]
        config = self._config or {}
        stored_records = len(self._records)
        devices = list(self._devices.values())[-30:]
        if self._storage_enabled:
            try:
                stored_records = self._storage.message_count()
                stored_devices = self._storage.recent_devices(30)
                if stored_devices:
                    devices = stored_devices
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_snapshot_failed error=%s", exc)
        active_devices = sum(
            1 for device in devices
            if device.get("health") == "active" or device.get("online") or "health" not in device
        )
        return {
            "ok": True,
            "state": "running" if enabled_services else "error" if errors else "standby",
            "services": enabled_services,
            "listeners": {
                name: {
                    "enabled": state.enabled,
                    "state": state.state,
                    "bind_host": state.bind_host,
                    "bind_hosts": state.bind_hosts or [],
                    "port": state.port,
                    "error": state.error,
                }
                for name, state in self._listeners.items()
            },
            "interfaces": self._interface_state,
            "active_http_endpoints": sum(1 for item in config.get("http_endpoints", []) if item.get("enabled")),
            "active_mqtt_topics": sum(1 for item in config.get("mqtt_topics", []) if item.get("enabled")),
            "stored_records": stored_records,
            "pending_forward": self._buffer["pending"],
            "connected_devices": active_devices,
            "buffer": dict(self._buffer),
            "devices": devices,
            "mqtt_sessions": list(self._mqtt_sessions.values())[-30:],
            "audit": {
                "total": len(self._events),
                "outages": sum(1 for event in self._events if event.get("type") == "outage"),
                "errors": sum(1 for event in self._events if event.get("type") == "error"),
                "auth_failures": sum(1 for event in self._events if event.get("type") == "auth_failure"),
                "events": audit_events,
            },
            "last_received_at": self._records[-1]["received_at"] if self._records else None,
            "tailscale_reachable": bool(self._interface_state.get("tailscale0", {}).get("ipv4")),
            "message": errors[0] if errors else "Listeners active" if enabled_services else "Configuration ready",
            "timestamp_ms": _now_ms(),
        }

    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def protocol_metrics(self, protocol_group: str) -> dict[str, Any]:
        if self._storage_enabled:
            try:
                return self._storage.protocol_metrics(protocol_group)
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_protocol_metrics_failed group=%s error=%s", protocol_group, exc)
        protocols = {"http": {"HTTP", "HTTPS"}, "mqtt": {"MQTT", "MQTTS"}}.get(protocol_group, set())
        records = [record for record in self._records if record.get("protocol") in protocols]
        events = [
            event for event in self._events
            if event.get("protocol") in protocols
            and (event.get("event_type") or event.get("type")) in ANOMALY_EVENT_TYPES
        ]
        route_counts: dict[str, dict[str, Any]] = {}
        for record in records:
            route = str(record.get("route") or "")
            route_counts.setdefault(route, {"route": route, "count": 0, "devices": set(), "last_seen": ""})
            route_counts[route]["count"] += 1
            route_counts[route]["devices"].add(str(record.get("device_id") or "unknown"))
            route_counts[route]["last_seen"] = str(record.get("received_at") or "")
        routes = [
            {**item, "devices": len(item["devices"])}
            for item in sorted(route_counts.values(), key=lambda row: row["count"], reverse=True)
        ]
        return {
            "ok": True,
            "protocol_group": protocol_group,
            "total_messages": len(records),
            "device_count": len({record.get("device_id") for record in records}),
            "avg_payload_size": 0,
            "max_payload_size": 0,
            "route_missing": 0,
            "auth_failures": 0,
            "routes": routes[:20],
            "minute_series": [],
            "recent_messages": [_export_memory_message(row, include_payload=False) for row in records[-20:]],
            "devices": _memory_protocol_devices(records),
            "anomaly_summary": _memory_anomaly_summary(events),
            "recent_events": [_export_memory_event(row) for row in events[-20:]],
        }

    def alert_metrics(self) -> dict[str, Any]:
        if self._storage_enabled:
            try:
                events = self._storage.alert_events(100)
                return {"ok": True, "summary": self._storage.alert_summary(), "events": events}
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_alert_metrics_failed error=%s", exc)
        events = [
            event for event in self._events
            if event.get("severity") in {"warning", "error", "critical"}
            or (event.get("event_type") or event.get("type")) in ANOMALY_EVENT_TYPES
        ][-100:]
        return {
            "ok": True,
            "summary": {
                "total": len(events),
                "info": sum(1 for event in events if event.get("severity") == "info"),
                "warning": sum(1 for event in events if event.get("severity") == "warning"),
                "error": sum(1 for event in events if event.get("severity") == "error"),
                "critical": sum(1 for event in events if event.get("severity") == "critical"),
            },
            "events": events,
        }

    def history_devices(self) -> dict[str, Any]:
        if self._storage_enabled:
            try:
                return {"ok": True, "devices": self._storage.history_devices()}
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_history_devices_failed error=%s", exc)
        devices = _memory_history_devices(list(self._records), list(self._events))
        return {"ok": True, "devices": devices}

    def device_history(self, device_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        if self._storage_enabled:
            try:
                return self._storage.device_history(device_id, filters)
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_device_history_failed device=%s error=%s", device_id, exc)
        return _memory_device_history(device_id, list(self._records), list(self._events), filters)

    def export_events(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        if self._storage_enabled:
            try:
                return self._storage.export_events(filters)
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_export_events_failed error=%s", exc)
        events = list(self._events)
        return [_export_memory_event(row) for row in _filter_export_rows(events, filters, timestamp_key="timestamp")]

    def export_messages(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        if self._storage_enabled:
            try:
                return self._storage.export_messages(filters)
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_export_messages_failed error=%s", exc)
        include_payload = _truthy(filters.get("include_payload"))
        rows = _filter_export_rows(list(self._records), filters, timestamp_key="received_at")
        if include_payload:
            return [_export_memory_message(row, include_payload=True) for row in rows]
        return [_export_memory_message(row, include_payload=False) for row in rows]

    async def _run(self) -> None:
        LOGGER.info("task_loop_started")
        while not self._stop_event.is_set():
            try:
                async with self._lock:
                    await self._reconcile_locked()
                    self._detect_silent_devices_locked()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._audit("error", "edge-server", f"reconcile failed: {exc}")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=5.0)
            except TimeoutError:
                continue

    async def _reconcile_locked(self) -> None:
        self._interface_state = _interfaces()
        self._log_interface_changes()
        config = self._config or {}
        listeners = config.get("listeners") or {}
        bind_hosts = _resolve_bind_hosts(listeners, self._interface_state)

        desired: dict[str, tuple[str, str, int, str, bool]] = {}
        for name in ("http", "https", "mqtt", "mqtts"):
            item = listeners.get(name) or {}
            state = self._listeners[name]
            state.enabled = bool(item.get("enabled"))
            state.port = int(item.get("port") or _default_port(name))
            state.bind_hosts = list(bind_hosts)
            state.bind_host = ", ".join(bind_hosts)
            if not state.enabled:
                state.state = "stopped"
                state.error = None
                for failed_id in [key for key in self._failed_keys if key.startswith(f"{name}@")]:
                    self._failed_keys.pop(failed_id, None)
                continue
            if not bind_hosts:
                state.state = "waiting"
                state.error = None
                continue
            for host in bind_hosts:
                server_id = _server_id(name, host)
                desired[server_id] = (server_id, host, state.port, name, bool(item.get("mtls_required")))

        for server_id in list(self._servers):
            if server_id not in desired or self._server_keys.get(server_id) != desired[server_id]:
                await self._stop_server(server_id)

        for server_id, key in desired.items():
            if server_id in self._servers:
                continue
            if self._failed_keys.get(server_id) == key:
                continue
            await self._start_server(server_id, key)

    async def _start_server(self, server_id: str, key: tuple[str, str, int, str, bool]) -> None:
        _server_id_value, host, port, protocol, mtls_required = key
        name = protocol
        state = self._listeners[name]
        state.state = "starting"
        state.error = None
        ssl_context = None
        if protocol in {"https", "mqtts"}:
            ssl_context = self._ssl_context(name, mtls_required)
            if ssl_context is None:
                state.state = "error"
                self._failed_keys[server_id] = key
                return
        try:
            handler = self._handle_http if protocol in {"http", "https"} else self._handle_mqtt
            server = await asyncio.start_server(
                lambda reader, writer: handler(protocol, reader, writer),
                host=host,
                port=port,
                ssl=ssl_context,
                start_serving=True,
            )
        except Exception as exc:
            state.error = str(exc)
            self._failed_keys[server_id] = key
            state.state = "running" if any(item.startswith(f"{name}@") for item in self._servers) else "error"
            self._audit("error", name, f"listener failed on {host}:{port}: {exc}")
            return
        self._servers[server_id] = server
        self._server_keys[server_id] = key
        self._failed_keys.pop(server_id, None)
        state.state = "running"
        LOGGER.info("listener_started listener=%s host=%s port=%d", name, host, port)

    def _ssl_context(self, listener_name: str, mtls_required: bool) -> ssl.SSLContext | None:
        tls = (self._config or {}).get("tls") or {}
        cert_dir = Path(str(tls.get("secrets_dir") or "/opt/metacrust/secrets/edge_server"))
        cert = cert_dir / str(tls.get("server_cert") or "server.crt")
        key = cert_dir / str(tls.get("server_key") or "server.key")
        client_ca = cert_dir / str(tls.get("client_ca") or "client-ca.crt")
        if not cert.exists() or not key.exists():
            message = "TLS listener requested but server certificate/key are not installed"
            self._audit("error", "tls", message)
            self._listeners[listener_name].error = message
            return None
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        if mtls_required:
            if not client_ca.exists():
                message = "mTLS requested but client CA is not installed"
                self._audit("error", "mtls", message)
                self._listeners[listener_name].error = message
                return None
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(cafile=str(client_ca))
        return context

    async def _stop_all(self) -> None:
        for name in list(self._servers):
            await self._stop_server(name)

    async def _stop_server(self, server_id: str) -> None:
        server = self._servers.pop(server_id, None)
        self._server_keys.pop(server_id, None)
        self._failed_keys.pop(server_id, None)
        if server is not None:
            server.close()
            await server.wait_closed()
            LOGGER.info("listener_stopped listener=%s", server_id)
        listener_name = server_id.split("@", 1)[0]
        listener = self._listeners[listener_name]
        if not listener.enabled and not any(key.startswith(f"{listener_name}@") for key in self._servers):
            listener.state = "stopped"

    async def _handle_http(self, protocol: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = _peer_name(writer)
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            header_text = head.decode("iso-8859-1", errors="replace")
            lines = header_text.split("\r\n")
            method, target, _version = lines[0].split(" ", 2)
            headers = _parse_headers(lines[1:])
            body_len = int(headers.get("content-length") or 0)
            body = await reader.readexactly(body_len) if body_len > 0 else b""
            endpoint = self._match_http_endpoint(protocol, method, urlsplit(target).path)
            if endpoint is None:
                self._buffer["dropped"] += 1
                self._record_event("route_missing", "warning", protocol.upper(), "unknown", urlsplit(target).path, peer, f"No HTTP endpoint for {method} {target}")
                await _http_response(writer, 404, {"ok": False, "message": "endpoint not found"})
                return
            if not self._http_authorized(endpoint, headers, writer):
                self._buffer["dropped"] += 1
                self._record_event(
                    "auth_failure",
                    "error",
                    protocol.upper(),
                    "unknown",
                    str(endpoint.get("path") or urlsplit(target).path),
                    peer,
                    f"HTTP auth failed for {endpoint.get('name')}",
                )
                await _http_response(writer, 401, {"ok": False, "message": "unauthorized"})
                return
            payload = _decode_payload(body, endpoint.get("payload_type"))
            device_id = _http_device_id(endpoint, headers, target, payload)
            record = _message_record(
                kind="http",
                protocol=protocol.upper(),
                device_id=device_id,
                identity_source=f"http:{endpoint.get('device_id_source') or 'payload'}",
                source_ip=peer,
                route=str(endpoint.get("path") or urlsplit(target).path),
                endpoint_name=str(endpoint.get("name") or ""),
                payload_type=str(endpoint.get("payload_type") or "json"),
                payload=payload,
                raw_payload=body,
            )
            self._record(record)
            LOGGER.info(
                "http_ingest accepted protocol=%s peer=%s device_id=%s endpoint=%s path=%s",
                protocol,
                peer,
                device_id,
                endpoint.get("name"),
                endpoint.get("path"),
            )
            await _http_response(writer, 200, {"ok": True, "message": "accepted", "device_id": device_id})
        except asyncio.IncompleteReadError:
            self._audit("error", peer, "HTTP client disconnected early")
        except Exception as exc:
            self._buffer["dropped"] += 1
            self._audit("error", peer, f"HTTP ingest failed: {exc}")
            try:
                await _http_response(writer, 400, {"ok": False, "message": "bad request"})
            except Exception:
                pass
        finally:
            writer.close()
            await _wait_closed(writer)

    def _match_http_endpoint(self, protocol: str, method: str, path: str) -> dict[str, Any] | None:
        for endpoint in (self._config or {}).get("http_endpoints") or []:
            if not endpoint.get("enabled"):
                continue
            if str(endpoint.get("protocol") or "http") != protocol:
                continue
            if str(endpoint.get("method") or "POST").upper() != method.upper():
                continue
            if _normal_path(str(endpoint.get("path") or "/ingest")) == _normal_path(path):
                return endpoint
        return None

    def _http_authorized(self, endpoint: dict[str, Any], headers: dict[str, str], writer: asyncio.StreamWriter) -> bool:
        auth = str(endpoint.get("auth") or "none")
        if auth == "none":
            return True
        if auth == "token":
            return headers.get("authorization", "").lower().startswith("bearer ")
        if auth == "mtls":
            ssl_object = writer.get_extra_info("ssl_object")
            return bool(ssl_object and ssl_object.getpeercert())
        return True

    async def _handle_mqtt(self, protocol: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = _peer_name(writer)
        client_id = peer
        clean_disconnect = False
        try:
            packet_type, _flags, body = await _read_mqtt_packet(reader)
            if packet_type != 1:
                raise ValueError("first MQTT packet must be CONNECT")
            connect = _parse_mqtt_connect(body)
            client_id = connect.get("client_id") or peer
            listener_cfg = ((self._config or {}).get("listeners") or {}).get(protocol) or {}
            if protocol == "mqtt" and not listener_cfg.get("allow_anonymous") and not connect.get("username"):
                writer.write(b"\x20\x02\x00\x04")
                await writer.drain()
                self._record_event("auth_failure", "error", protocol.upper(), client_id, "", client_id, "MQTT anonymous connection rejected")
                return
            writer.write(b"\x20\x02\x00\x00")
            await writer.drain()
            self._mqtt_sessions[client_id] = {
                "client_id": client_id,
                "protocol": protocol.upper(),
                "peer": peer,
                "connected_at": _utc_now(),
                "status": "online",
            }
            self._mqtt_client_devices[client_id] = set()
            self._track_mqtt_connect(protocol.upper(), client_id, peer)
            LOGGER.info("mqtt_client_connected protocol=%s client_id=%s peer=%s", protocol, client_id, peer)

            while True:
                packet_type, flags, body = await _read_mqtt_packet(reader)
                if packet_type == 3:
                    topic, payload, packet_id = _parse_mqtt_publish(flags, body)
                    matched = self._match_mqtt_topic(protocol, topic)
                    if matched is None:
                        self._buffer["dropped"] += 1
                        self._record_event("route_missing", "warning", protocol.upper(), client_id, topic, client_id, f"No MQTT topic filter for {topic}")
                    else:
                        decoded = _decode_payload(payload, matched.get("payload_type"))
                        device_id = _mqtt_device_id(matched, topic, decoded, client_id)
                        self._mqtt_client_devices.setdefault(client_id, set()).add(device_id)
                        record = _message_record(
                            kind="mqtt",
                            protocol=protocol.upper(),
                            device_id=device_id,
                            identity_source=f"mqtt:{matched.get('device_id_source') or 'topic_segment'}",
                            source_ip=peer,
                            route=topic,
                            endpoint_name=str(matched.get("name") or matched.get("topic_filter") or ""),
                            payload_type=str(matched.get("payload_type") or "json"),
                            payload=decoded,
                            raw_payload=payload,
                            extra={"client_id": client_id, "topic_filter": matched.get("topic_filter")},
                        )
                        self._record(record)
                        LOGGER.info(
                            "mqtt_ingest accepted protocol=%s peer=%s client_id=%s device_id=%s topic=%s",
                            protocol,
                            peer,
                            client_id,
                            device_id,
                            topic,
                        )
                    qos = (flags >> 1) & 0x03
                    if qos == 1 and packet_id is not None:
                        writer.write(b"\x40\x02" + packet_id.to_bytes(2, "big"))
                        await writer.drain()
                    elif qos == 2 and packet_id is not None:
                        writer.write(b"\x50\x02" + packet_id.to_bytes(2, "big"))
                        await writer.drain()
                elif packet_type == 8:
                    packet_id = int.from_bytes(body[:2], "big") if len(body) >= 2 else 1
                    writer.write(b"\x90\x03" + packet_id.to_bytes(2, "big") + b"\x00")
                    await writer.drain()
                elif packet_type == 12:
                    writer.write(b"\xd0\x00")
                    await writer.drain()
                elif packet_type == 14:
                    clean_disconnect = True
                    return
        except asyncio.IncompleteReadError:
            return
        except Exception as exc:
            self._buffer["dropped"] += 1
            self._audit("error", client_id, f"MQTT ingest failed: {exc}")
        finally:
            if client_id in self._mqtt_sessions:
                self._mqtt_sessions[client_id]["status"] = "disconnected"
                self._mqtt_sessions[client_id]["disconnected_at"] = _utc_now()
            device_ids = sorted(self._mqtt_client_devices.pop(client_id, set()))
            if client_id != peer:
                self._record_mqtt_disconnect(client_id, protocol.upper(), peer, clean_disconnect, device_ids)
            writer.close()
            await _wait_closed(writer)

    def _match_mqtt_topic(self, protocol: str, topic: str) -> dict[str, Any] | None:
        for item in (self._config or {}).get("mqtt_topics") or []:
            if not item.get("enabled"):
                continue
            if str(item.get("protocol") or "mqtt") != protocol:
                continue
            if _mqtt_match(str(item.get("topic_filter") or ""), topic):
                return item
        return None

    def _record(self, record: dict[str, Any]) -> None:
        self._records.append(record)
        self._buffer["pending"] += 1
        self._buffer["processed"] += 1
        if self._storage_enabled:
            try:
                record["record_id"], events = self._storage.save_message(record)
                for event in events:
                    self._append_event(event)
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_save_message_failed error=%s", exc)
        self._upsert_device(
            str(record.get("device_id") or "unknown"),
            str(record.get("protocol") or "unknown"),
            str(record.get("route") or ""),
            str(record.get("source_ip") or ""),
        )

    def _detect_silent_devices_locked(self) -> None:
        if not self._storage_enabled:
            return
        try:
            for event in self._storage.detect_device_silence():
                self._append_event(event)
        except Exception as exc:
            self._storage_enabled = False
            LOGGER.error("storage_detect_silence_failed error=%s", exc)

    def _track_mqtt_connect(self, protocol: str, client_id: str, peer: str) -> None:
        now = time.monotonic()
        history = self._mqtt_connect_history.setdefault(client_id, deque(maxlen=10))
        history.append(now)
        while history and now - history[0] > 60.0:
            history.popleft()
        if len(history) >= 4:
            self._record_event(
                "mqtt_reconnect_storm",
                "warning",
                protocol,
                client_id,
                "",
                client_id,
                f"MQTT client reconnecting repeatedly: {client_id}",
                {"source_ip": peer, "connects_in_60s": len(history)},
            )

    def _upsert_device(self, device_id: str, protocol: str, endpoint: str, peer: str) -> None:
        is_mqtt = protocol.upper() in {"MQTT", "MQTTS"}
        self._devices[device_id] = {
            "device_id": device_id,
            "protocol": protocol,
            "endpoint": endpoint,
            "peer": peer,
            "last_seen": _utc_now(),
            "online": is_mqtt,
            "health": "active",
            "health_label": "Connected" if is_mqtt else "Receiving data",
        }

    def _audit(self, event_type: str, source: str, message: str) -> None:
        event = {
            "type": event_type,
            "source": source,
            "message": message,
            "timestamp": _utc_now(),
            "severity": _event_severity(event_type),
        }
        self._events.append(event)
        level = logging.ERROR if event_type in {"error", "auth_failure", "outage"} else logging.INFO
        LOGGER.log(level, "audit type=%s source=%s message=%s", event_type, source, message)
        if self._storage_enabled:
            try:
                self._storage.save_event(event)
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_save_event_failed error=%s", exc)

    def _append_event(self, event: dict[str, Any]) -> None:
        self._events.append({
            "type": event.get("type") or event.get("event_type"),
            "source": event.get("source") or event.get("device_id"),
            "message": event.get("message"),
            "timestamp": event.get("timestamp") or event.get("created_at") or _utc_now(),
            "severity": event.get("severity") or "info",
            "protocol": event.get("protocol"),
            "device_id": event.get("device_id"),
            "route": event.get("route"),
        })
        level = logging.WARNING if event.get("severity") == "warning" else logging.INFO
        LOGGER.log(
            level,
            "event type=%s source=%s message=%s",
            event.get("type") or event.get("event_type"),
            event.get("source") or event.get("device_id"),
            event.get("message"),
        )

    def _record_mqtt_disconnect(
        self,
        client_id: str,
        protocol: str,
        peer: str,
        clean: bool,
        device_ids: list[str] | None = None,
    ) -> None:
        targets = sorted({client_id, *(device_ids or [])})
        event = {
            "type": "mqtt_disconnected",
            "event_type": "mqtt_disconnected",
            "severity": "info" if clean else "warning",
            "protocol": protocol,
            "device_id": client_id,
            "route": "",
            "source": client_id,
            "message": f"MQTT client {'cleanly disconnected' if clean else 'disconnected'}: {client_id}",
            "timestamp": _utc_now(),
            "details": {"source_ip": peer, "clean": clean, "device_ids": targets},
        }
        for device_id in targets:
            if device_id in self._devices:
                self._devices[device_id]["online"] = False
                self._devices[device_id]["health"] = "disconnected"
                self._devices[device_id]["health_label"] = "Disconnected"
                self._devices[device_id]["last_disconnected_at"] = event["timestamp"]
        if not clean:
            self._append_event(event)
        if self._storage_enabled:
            try:
                self._storage.mark_mqtt_disconnected(client_id, protocol, peer, clean, targets)
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_mqtt_disconnect_failed error=%s", exc)

    def _record_event(
        self,
        event_type: str,
        severity: str,
        protocol: str,
        device_id: str,
        route: str,
        source: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "type": event_type,
            "event_type": event_type,
            "severity": severity,
            "protocol": protocol,
            "device_id": device_id,
            "route": route,
            "source": source,
            "message": message,
            "timestamp": _utc_now(),
            "details": details or {},
        }
        self._append_event(event)
        if self._storage_enabled:
            try:
                self._storage.save_event(event)
            except Exception as exc:
                self._storage_enabled = False
                LOGGER.error("storage_record_event_failed error=%s", exc)

    def _log_interface_changes(self) -> None:
        parts = []
        for name in sorted(self._interface_state):
            item = self._interface_state[name]
            if name in {"lo", "eth0", "eth1", "wlan0", "wwan0", "tailscale0"} or item.get("ipv4"):
                parts.append(f"{name}:up={item.get('up')} ipv4={item.get('ipv4') or '-'}")
        signature = ";".join(parts)
        if signature != self._interface_signature:
            self._interface_signature = signature
            LOGGER.info("interfaces %s", signature or "none")


def _interfaces() -> dict[str, Any]:
    result: dict[str, Any] = {}
    names = {name for _, name in socket.if_nameindex()}
    try:
        completed = subprocess.run(["ip", "-j", "addr", "show"], check=False, capture_output=True, text=True, timeout=2)
        payload = json.loads(completed.stdout or "[]") if completed.returncode == 0 else []
    except Exception:
        payload = []
    for item in payload:
        name = item.get("ifname")
        if not name:
            continue
        addrs = item.get("addr_info") or []
        result[name] = {
            "up": "UP" in (item.get("flags") or []),
            "ipv4": next((addr.get("local") for addr in addrs if addr.get("family") == "inet"), ""),
            "ipv6": next((addr.get("local") for addr in addrs if addr.get("family") == "inet6"), ""),
        }
    for name in names:
        result.setdefault(name, {"up": True, "ipv4": "", "ipv6": ""})
    return result


def _filter_export_rows(rows: list[dict[str, Any]], filters: dict[str, Any], *, timestamp_key: str) -> list[dict[str, Any]]:
    protocol_group = str(filters.get("protocol_group") or "").lower()
    protocol_set = {"HTTP", "HTTPS"} if protocol_group == "http" else {"MQTT", "MQTTS"} if protocol_group == "mqtt" else None
    protocol = str(filters.get("protocol") or "").upper()
    device_id = str(filters.get("device_id") or "")
    route = str(filters.get("route") or "")
    event_type = str(filters.get("event_type") or "")
    severity = str(filters.get("severity") or "")
    payload_type = str(filters.get("payload_type") or "")
    from_value = str(filters.get("from") or "")
    to_value = str(filters.get("to") or "")
    accepted = filters.get("accepted")
    accepted_value = None if accepted in (None, "") else _truthy(accepted)
    limit = _limit(filters.get("limit"))
    result = []
    for row in reversed(rows):
        row_protocol = str(row.get("protocol") or "").upper()
        row_time = str(row.get(timestamp_key) or row.get("created_at") or "")
        if protocol_set and row_protocol not in protocol_set:
            continue
        if protocol and row_protocol != protocol:
            continue
        if device_id and str(row.get("device_id") or "") != device_id:
            continue
        if route and str(row.get("route") or "") != route:
            continue
        if event_type and str(row.get("event_type") or row.get("type") or "") != event_type:
            continue
        if severity and str(row.get("severity") or "") != severity:
            continue
        if payload_type and str(row.get("payload_type") or "") != payload_type:
            continue
        if accepted_value is not None and bool(row.get("accepted", True)) != accepted_value:
            continue
        if from_value and row_time < from_value:
            continue
        if to_value and row_time > to_value:
            continue
        result.append(row)
        if len(result) >= limit:
            break
    return result


def _memory_protocol_devices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for row in rows:
        device_id = str(row.get("device_id") or "unknown")
        counts[device_id] = counts.get(device_id, 0) + 1
        latest[device_id] = row
    return [
        {
            "device_id": device_id,
            "protocol": row.get("protocol"),
            "endpoint": row.get("route"),
            "peer": row.get("source_ip"),
            "last_seen": row.get("received_at"),
            "message_count": counts.get(device_id, 0),
            "health": "active",
            "health_label": "Connected" if str(row.get("protocol") or "").upper() in {"MQTT", "MQTTS"} else "Receiving data",
            "anomaly_count": 0,
        }
        for device_id, row in latest.items()
    ][-50:]


def _memory_anomaly_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        event_type = str(row.get("event_type") or row.get("type") or "event")
        severity = str(row.get("severity") or "info")
        key = (event_type, severity)
        item = summary.setdefault(
            key,
            {"event_type": event_type, "severity": severity, "count": 0, "last_seen": ""},
        )
        item["count"] += 1
        item["last_seen"] = str(row.get("created_at") or row.get("timestamp") or item["last_seen"])
    return sorted(summary.values(), key=lambda item: int(item["count"]), reverse=True)[:20]


def _memory_history_devices(records: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    first_seen: dict[str, str] = {}
    for row in records:
        device_id = str(row.get("device_id") or "unknown")
        counts[device_id] = counts.get(device_id, 0) + 1
        first_seen.setdefault(device_id, str(row.get("received_at") or ""))
        latest[device_id] = row
    for event in events:
        device_id = str(event.get("device_id") or event.get("source") or "unknown")
        event_counts[device_id] = event_counts.get(device_id, 0) + 1
    result = []
    for device_id, row in latest.items():
        protocol = str(row.get("protocol") or "")
        result.append({
            "device_id": device_id,
            "protocol": protocol,
            "first_seen": first_seen.get(device_id),
            "last_seen": row.get("received_at"),
            "last_route": row.get("route"),
            "message_count": counts.get(device_id, 0),
            "event_count": event_counts.get(device_id, 0),
            "anomaly_count": event_counts.get(device_id, 0),
            "health": "active",
            "health_label": "Connected" if protocol in {"MQTT", "MQTTS"} else "Receiving data",
        })
    return sorted(result, key=lambda item: str(item.get("last_seen") or ""), reverse=True)


def _memory_device_history(
    device_id: str,
    records: list[dict[str, Any]],
    events: list[dict[str, Any]],
    filters: dict[str, Any],
) -> dict[str, Any]:
    protocol_group = str(filters.get("protocol_group") or "").lower()
    protocol_set = {"HTTP", "HTTPS"} if protocol_group == "http" else {"MQTT", "MQTTS"} if protocol_group == "mqtt" else None
    device_records = [
        row for row in records
        if str(row.get("device_id") or "") == device_id
        and (not protocol_set or str(row.get("protocol") or "") in protocol_set)
    ]
    device_events = [
        row for row in events
        if str(row.get("device_id") or row.get("source") or "") == device_id
        and (not protocol_set or str(row.get("protocol") or "") in protocol_set)
    ]
    buckets: dict[str, dict[str, Any]] = {}
    for row in device_records:
        bucket = str(row.get("received_at") or "")[:16]
        item = buckets.setdefault(bucket, {"bucket": bucket, "count": 0, "avg_payload_size": 0.0, "max_payload_size": 0})
        count = int(item["count"]) + 1
        payload_size = int(row.get("payload_size") or 0)
        item["avg_payload_size"] = ((float(item["avg_payload_size"]) * (count - 1)) + payload_size) / count
        item["max_payload_size"] = max(int(item["max_payload_size"] or 0), payload_size)
        item["count"] = count
    anomaly_buckets: dict[str, dict[str, Any]] = {}
    for event in device_events:
        bucket = str(event.get("created_at") or event.get("timestamp") or "")[:16]
        anomaly_buckets.setdefault(bucket, {"bucket": bucket, "count": 0})["count"] += 1
    latest = device_records[-1] if device_records else {}
    total_payload = sum(int(row.get("payload_size") or 0) for row in device_records)
    return {
        "ok": True,
        "device_id": device_id,
        "device": {
            "device_id": device_id,
            "protocol": latest.get("protocol"),
            "first_seen": device_records[0].get("received_at") if device_records else None,
            "last_seen": latest.get("received_at"),
            "last_route": latest.get("route"),
            "health": "active" if device_records else "stale",
            "health_label": "Stored in memory" if device_records else "No stored data",
        },
        "summary": {
            "total_messages": len(device_records),
            "first_message_at": device_records[0].get("received_at") if device_records else None,
            "last_message_at": latest.get("received_at"),
            "avg_payload_size": total_payload / len(device_records) if device_records else 0,
            "max_payload_size": max((int(row.get("payload_size") or 0) for row in device_records), default=0),
            "event_count": len(device_events),
        },
        "message_series": sorted(buckets.values(), key=lambda item: item["bucket"]),
        "payload_series": sorted(buckets.values(), key=lambda item: item["bucket"]),
        "anomaly_series": sorted(anomaly_buckets.values(), key=lambda item: item["bucket"]),
        "routes": [],
        "event_summary": _memory_anomaly_summary(device_events),
        "recent_events": [_export_memory_event(row) for row in device_events[-50:]],
        "recent_messages": [_export_memory_message(row, include_payload=False) for row in device_records[-50:]],
    }


def _export_memory_message(row: dict[str, Any], *, include_payload: bool) -> dict[str, Any]:
    item = {
        "received_at": row.get("received_at"),
        "protocol": row.get("protocol"),
        "device_id": row.get("device_id"),
        "identity_source": row.get("identity_source"),
        "source_ip": row.get("source_ip"),
        "route": row.get("route"),
        "endpoint_name": row.get("endpoint_name"),
        "payload_type": row.get("payload_type"),
        "payload_size": row.get("payload_size"),
        "payload_hash": row.get("payload_hash"),
        "device_timestamp": row.get("device_timestamp"),
        "sequence": row.get("sequence"),
        "accepted": row.get("accepted"),
        "reject_reason": row.get("reject_reason"),
        "details_json": row.get("details_json"),
    }
    if include_payload:
        item["payload_json"] = row.get("payload_json")
        raw = row.get("payload_raw")
        if raw is not None:
            item["payload_raw_hex"] = bytes(raw).hex()
    return item


def _export_memory_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "created_at": row.get("created_at") or row.get("timestamp"),
        "severity": row.get("severity"),
        "event_type": row.get("event_type") or row.get("type"),
        "protocol": row.get("protocol"),
        "device_id": row.get("device_id"),
        "route": row.get("route"),
        "source": row.get("source"),
        "message": row.get("message"),
        "details_json": row.get("details_json") or row.get("details"),
    }


def _limit(value: Any) -> int:
    try:
        return max(1, min(100_000, int(value or 1000)))
    except (TypeError, ValueError):
        return 1000


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "accepted", "include"}


def _message_record(
    *,
    kind: str,
    protocol: str,
    device_id: str,
    identity_source: str,
    source_ip: str,
    route: str,
    endpoint_name: str,
    payload_type: str,
    payload: Any,
    raw_payload: bytes,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    received_at = _utc_now()
    record = {
        "kind": kind,
        "protocol": protocol,
        "device_id": device_id or "unknown",
        "identity_source": identity_source,
        "source_ip": source_ip,
        "peer": source_ip,
        "route": route,
        "endpoint_name": endpoint_name,
        "payload_type": payload_type,
        "payload_size": len(raw_payload),
        "payload_hash": hashlib.sha256(raw_payload).hexdigest(),
        "payload": payload,
        "payload_json": payload if isinstance(payload, (dict, list)) else None,
        "payload_schema": _payload_schema(payload),
        "payload_parse_error": payload.get("_edge_parse_error") if isinstance(payload, dict) else None,
        "payload_raw": raw_payload,
        "device_timestamp": _extract_device_timestamp(payload),
        "sequence": _extract_sequence(payload),
        "accepted": True,
        "reject_reason": None,
        "received_at": received_at,
        "details_json": extra or {},
    }
    if kind == "http":
        record["path"] = route
        record["endpoint"] = endpoint_name
    elif kind == "mqtt":
        record["topic"] = route
        record["filter"] = (extra or {}).get("topic_filter")
    return record


def _payload_schema(payload: Any) -> str:
    if isinstance(payload, dict):
        keys = sorted(str(key) for key in payload if not str(key).startswith("_edge_"))
        return "json:" + ",".join(keys)
    if isinstance(payload, list):
        return "json:list"
    if payload is None:
        return "empty"
    return type(payload).__name__


def _extract_sequence(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("sequence", "seq", "message_id", "msg_id", "counter", "count"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _extract_device_timestamp(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("timestamp", "time", "ts", "created_at", "sent_at", "device_timestamp"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _resolve_bind_hosts(listeners: dict[str, Any], interfaces: dict[str, Any]) -> list[str]:
    selected = listeners.get("bind_interfaces")
    allowed = {"eth0", "eth1", "wlan0", "wwan0"}
    if selected is None:
        selected = ["eth0", "eth1", "wlan0", "wwan0"]
    elif not isinstance(selected, list):
        selected = []
    selected_names = [str(name) for name in selected if str(name) in allowed]

    hosts: list[str] = []
    for name in selected_names:
        item = interfaces.get(name) or {}
        if not item.get("up"):
            continue
        ipv4 = str(item.get("ipv4") or "")
        if ipv4 and ipv4 not in hosts:
            hosts.append(ipv4)
    return hosts


def _server_id(listener_name: str, host: str) -> str:
    return f"{listener_name}@{host}"


def _default_port(name: str) -> int:
    return {"http": 8080, "https": 8443, "mqtt": 1883, "mqtts": 8883}[name]


def _event_severity(event_type: str) -> str:
    if event_type in {"error", "auth_failure", "outage", "storage_error"}:
        return "error"
    if event_type in {
        "no_data_timeout",
        "route_missing",
        "message_gap",
        "rate_slowdown",
        "payload_parse_error",
        "payload_size_change",
        "payload_schema_change",
        "sequence_gap",
        "sequence_duplicate",
        "sequence_out_of_order",
        "device_clock_drift",
        "device_timestamp_stale",
        "mqtt_disconnected",
        "mqtt_reconnect_storm",
    }:
        return "warning"
    return "info"


def _parse_headers(lines: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in lines:
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def _decode_payload(body: bytes, payload_type: str | None) -> Any:
    if payload_type == "json":
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return {
                "_edge_parse_error": "invalid_json",
                "raw": body.decode("utf-8", errors="replace"),
            }
    if payload_type == "form":
        return body.decode("utf-8", errors="replace")
    return body.decode("utf-8", errors="replace")


def _http_device_id(endpoint: dict[str, Any], headers: dict[str, str], target: str, payload: Any) -> str:
    source = str(endpoint.get("device_id_source") or "payload")
    key = str(endpoint.get("device_id_key") or "device_id")
    if source == "header":
        return headers.get(key.lower(), "unknown")
    if source == "path":
        parts = [part for part in urlsplit(target).path.split("/") if part]
        if key.isdigit() and int(key) < len(parts):
            return parts[int(key)]
        return parts[-1] if parts else "unknown"
    if source == "fixed":
        return key or "fixed"
    if isinstance(payload, dict):
        return str(payload.get(key) or payload.get("device_id") or "unknown")
    return "unknown"


def _mqtt_device_id(config: dict[str, Any], topic: str, payload: Any, client_id: str) -> str:
    source = str(config.get("device_id_source") or "topic_segment")
    key = str(config.get("device_id_key") or "1")
    if source == "client_id":
        return client_id
    if source == "payload" and isinstance(payload, dict):
        return str(payload.get(key) or payload.get("device_id") or "unknown")
    if source == "fixed":
        return key or "fixed"
    parts = topic.split("/")
    if key.isdigit() and int(key) < len(parts):
        return parts[int(key)]
    return parts[-1] if parts else "unknown"


def _normal_path(path: str) -> str:
    return "/" + path.strip("/")


async def _http_response(writer: asyncio.StreamWriter, status_code: int, payload: dict[str, Any]) -> None:
    reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found"}.get(status_code, "OK")
    body = json.dumps(payload).encode("utf-8")
    header = (
        f"HTTP/1.1 {status_code} {reason}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    )
    writer.write(header.encode("utf-8") + body)
    await writer.drain()


async def _read_mqtt_packet(reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
    first = await reader.readexactly(1)
    packet_type = first[0] >> 4
    flags = first[0] & 0x0F
    multiplier = 1
    remaining = 0
    while True:
        encoded = (await reader.readexactly(1))[0]
        remaining += (encoded & 127) * multiplier
        if (encoded & 128) == 0:
            break
        multiplier *= 128
        if multiplier > 128 * 128 * 128:
            raise ValueError("malformed MQTT remaining length")
    return packet_type, flags, await reader.readexactly(remaining)


def _parse_mqtt_connect(body: bytes) -> dict[str, Any]:
    pos = 0
    protocol, pos = _mqtt_string(body, pos)
    if protocol not in {"MQTT", "MQIsdp"}:
        raise ValueError("unsupported MQTT protocol")
    _level = body[pos]
    flags = body[pos + 1]
    pos += 4
    client_id, pos = _mqtt_string(body, pos)
    if flags & 0x04:
        _will_topic, pos = _mqtt_string(body, pos)
        _will_payload, pos = _mqtt_string(body, pos)
    username = None
    if flags & 0x80:
        username, pos = _mqtt_string(body, pos)
    if flags & 0x40:
        _password, pos = _mqtt_string(body, pos)
    return {"client_id": client_id, "username": username}


def _parse_mqtt_publish(flags: int, body: bytes) -> tuple[str, bytes, int | None]:
    topic, pos = _mqtt_string(body, 0)
    qos = (flags >> 1) & 0x03
    packet_id = None
    if qos:
        packet_id = int.from_bytes(body[pos:pos + 2], "big")
        pos += 2
    return topic, body[pos:], packet_id


def _mqtt_string(body: bytes, pos: int) -> tuple[str, int]:
    if pos + 2 > len(body):
        raise ValueError("truncated MQTT string")
    size = int.from_bytes(body[pos:pos + 2], "big")
    pos += 2
    value = body[pos:pos + size].decode("utf-8", errors="replace")
    return value, pos + size


def _mqtt_match(filter_text: str, topic: str) -> bool:
    f_parts = filter_text.split("/")
    t_parts = topic.split("/")
    for idx, part in enumerate(f_parts):
        if part == "#":
            return True
        if idx >= len(t_parts):
            return False
        if part != "+" and part != t_parts[idx]:
            return False
    return len(f_parts) == len(t_parts)


def _peer_name(writer: asyncio.StreamWriter) -> str:
    peer = writer.get_extra_info("peername")
    if isinstance(peer, tuple) and peer:
        return str(peer[0])
    return "unknown"


async def _wait_closed(writer: asyncio.StreamWriter) -> None:
    try:
        await writer.wait_closed()
    except Exception:
        pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
