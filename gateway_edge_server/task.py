from __future__ import annotations

import asyncio
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

    def start(self, config: dict[str, Any]) -> None:
        self._config = deepcopy(config)
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
            "stored_records": len(self._records),
            "pending_forward": self._buffer["pending"],
            "connected_devices": len(self._devices),
            "buffer": dict(self._buffer),
            "devices": list(self._devices.values())[-30:],
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

    async def _run(self) -> None:
        LOGGER.info("task_loop_started")
        while not self._stop_event.is_set():
            try:
                async with self._lock:
                    await self._reconcile_locked()
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
        self._audit("listener", name, f"{name.upper()} listening on {host}:{port}")

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
                self._audit("error", peer, f"no HTTP endpoint for {method} {target}")
                await _http_response(writer, 404, {"ok": False, "message": "endpoint not found"})
                return
            if not self._http_authorized(endpoint, headers, writer):
                self._buffer["dropped"] += 1
                self._audit("auth_failure", peer, f"HTTP auth failed for {endpoint.get('name')}")
                await _http_response(writer, 401, {"ok": False, "message": "unauthorized"})
                return
            payload = _decode_payload(body, endpoint.get("payload_type"))
            device_id = _http_device_id(endpoint, headers, target, payload)
            record = {
                "kind": "http",
                "protocol": protocol.upper(),
                "endpoint": endpoint.get("name"),
                "path": endpoint.get("path"),
                "device_id": device_id,
                "payload": payload,
                "received_at": _utc_now(),
                "peer": peer,
            }
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
                self._audit("auth_failure", client_id, "MQTT anonymous connection rejected")
                return
            writer.write(b"\x20\x02\x00\x00")
            await writer.drain()
            self._upsert_device(client_id, protocol.upper(), "", peer)

            while True:
                packet_type, flags, body = await _read_mqtt_packet(reader)
                if packet_type == 3:
                    topic, payload, packet_id = _parse_mqtt_publish(flags, body)
                    matched = self._match_mqtt_topic(protocol, topic)
                    if matched is None:
                        self._buffer["dropped"] += 1
                        self._audit("error", client_id, f"no MQTT topic filter for {topic}")
                    else:
                        decoded = _decode_payload(payload, matched.get("payload_type"))
                        device_id = _mqtt_device_id(matched, topic, decoded, client_id)
                        record = {
                            "kind": "mqtt",
                            "protocol": protocol.upper(),
                            "topic": topic,
                            "filter": matched.get("topic_filter"),
                            "device_id": device_id,
                            "payload": decoded,
                            "received_at": _utc_now(),
                            "peer": peer,
                        }
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
                    return
        except asyncio.IncompleteReadError:
            return
        except Exception as exc:
            self._buffer["dropped"] += 1
            self._audit("error", client_id, f"MQTT ingest failed: {exc}")
        finally:
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
        self._upsert_device(
            str(record.get("device_id") or "unknown"),
            str(record.get("protocol") or "unknown"),
            str(record.get("path") or record.get("topic") or ""),
            str(record.get("peer") or ""),
        )

    def _upsert_device(self, device_id: str, protocol: str, endpoint: str, peer: str) -> None:
        self._devices[device_id] = {
            "device_id": device_id,
            "protocol": protocol,
            "endpoint": endpoint,
            "peer": peer,
            "last_seen": _utc_now(),
        }

    def _audit(self, event_type: str, source: str, message: str) -> None:
        event = {
            "type": event_type,
            "source": source,
            "message": message,
            "timestamp": _utc_now(),
        }
        self._events.append(event)
        level = logging.ERROR if event_type in {"error", "auth_failure", "outage"} else logging.INFO
        LOGGER.log(level, "audit type=%s source=%s message=%s", event_type, source, message)

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
            return {"raw": body.decode("utf-8", errors="replace")}
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
