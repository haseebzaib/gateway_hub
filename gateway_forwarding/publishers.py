"""Upstream publishers: MQTT (paho) and HTTPS (REST / GraphQL via httpx).

Both expose small synchronous APIs; the service calls them from worker
coroutines via asyncio.to_thread so a slow broker never blocks the event loop.
Imports of paho/httpx are lazy so the hub still runs on machines without them
(the profile then reports the missing dependency as its status error).
"""

from __future__ import annotations

import json
import ssl
import threading
from pathlib import Path
from typing import Any


PUBLISH_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 10.0


def build_ssl_context(
    ca_path: Path | None,
    cert_path: Path | None,
    key_path: Path | None,
    verify: bool = True,
) -> ssl.SSLContext:
    if verify and ca_path is not None:
        context = ssl.create_default_context(cafile=str(ca_path))
    else:
        context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if cert_path is not None and key_path is not None:
        context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return context


class MqttPublisher:
    """One MQTT connection with an availability Last-Will on the status topic."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        username: str = "",
        password: str = "",
        qos: int = 1,
        ssl_context: ssl.SSLContext | None = None,
        status_topic: str | None = None,
        client_id: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.qos = qos
        self.status_topic = status_topic
        self.last_error: str | None = None
        self._connected = threading.Event()
        try:
            import paho.mqtt.client as mqtt  # lazy: optional on dev machines
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is not installed on this system") from exc

        try:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id=client_id or None
            )
        except (AttributeError, TypeError):  # paho 1.x on the device image
            self._client = mqtt.Client(client_id=client_id or None)
        if username:
            self._client.username_pw_set(username, password or None)
        if ssl_context is not None:
            self._client.tls_set_context(ssl_context)
        if status_topic:
            self._client.will_set(status_topic, payload="offline", qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    # paho invokes these from its network thread (signatures differ 1.x/2.x)
    def _on_connect(self, *args: Any, **kwargs: Any) -> None:
        self._connected.set()
        if self.status_topic:
            try:
                self._client.publish(self.status_topic, payload="online", qos=1, retain=True)
            except Exception:
                pass

    def _on_disconnect(self, *args: Any, **kwargs: Any) -> None:
        self._connected.clear()

    def connect(self) -> None:
        """Blocking connect; raises RuntimeError with a readable reason."""
        try:
            self._client.connect(self.host, self.port, keepalive=30)
        except Exception as exc:
            raise RuntimeError(f"connect to {self.host}:{self.port} failed: {exc}") from exc
        self._client.loop_start()
        if not self._connected.wait(CONNECT_TIMEOUT_S):
            self.close()
            raise RuntimeError(f"broker {self.host}:{self.port} did not accept the connection")

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish one envelope; raises on failure so the cursor is not advanced."""
        if not self._connected.is_set():
            raise RuntimeError("not connected")
        info = self._client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=self.qos)
        info.wait_for_publish(timeout=PUBLISH_TIMEOUT_S)
        if not info.is_published():
            raise RuntimeError(f"publish to {topic} timed out")

    def close(self) -> None:
        try:
            if self.status_topic and self._connected.is_set():
                info = self._client.publish(self.status_topic, payload="offline", qos=1, retain=True)
                info.wait_for_publish(timeout=2.0)
        except Exception:
            pass
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        self._connected.clear()


class HttpsPublisher:
    """POSTs batches of envelopes to one endpoint, as REST array or GraphQL."""

    def __init__(
        self,
        url: str,
        *,
        mode: str = "rest",
        graphql_query: str = "",
        auth: dict[str, Any] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        verify_tls: bool = True,
        gateway_id: str = "",
    ) -> None:
        try:
            import httpx  # lazy
        except ImportError as exc:
            raise RuntimeError("httpx is not installed on this system") from exc

        self.url = url
        self.mode = mode
        self.graphql_query = graphql_query
        self.last_error: str | None = None

        headers = {"Content-Type": "application/json"}
        if gateway_id:
            headers["X-Gateway-Id"] = gateway_id
        auth = auth or {}
        basic_auth = None
        kind = auth.get("type", "none")
        if kind == "bearer" and auth.get("token"):
            headers["Authorization"] = f"Bearer {auth['token']}"
        elif kind == "basic":
            basic_auth = (auth.get("username", ""), auth.get("password", ""))
        elif kind == "header" and auth.get("header_name"):
            headers[auth["header_name"]] = auth.get("header_value", "")

        verify: Any = ssl_context if ssl_context is not None else verify_tls
        self._client = httpx.Client(
            headers=headers, auth=basic_auth, verify=verify, timeout=PUBLISH_TIMEOUT_S
        )

    def post(self, envelopes: list[dict[str, Any]]) -> None:
        """Deliver a batch; raises with a readable reason on any failure."""
        if self.mode == "graphql":
            body: Any = {"query": self.graphql_query, "variables": {"events": envelopes}}
        else:
            body = envelopes
        try:
            response = self._client.post(self.url, json=body)
        except Exception as exc:
            raise RuntimeError(f"POST {self.url} failed: {exc}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"{self.url} answered HTTP {response.status_code}")
        if self.mode == "graphql":
            # GraphQL reports failures inside a 200 response
            try:
                data = response.json()
            except ValueError:
                return
            errors = data.get("errors") if isinstance(data, dict) else None
            if errors:
                first = errors[0] if isinstance(errors, list) and errors else errors
                message = first.get("message") if isinstance(first, dict) else str(first)
                raise RuntimeError(f"GraphQL rejected the batch: {message}")
        self.last_status_code = response.status_code

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
