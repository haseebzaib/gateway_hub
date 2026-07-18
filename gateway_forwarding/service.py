"""The forwarding engine: one async worker per enabled profile.

Data is never copied into an outbox — workers tail the existing durable
stores (gateway_interfaces sensor_messages, monitor anomaly_events) with a
per-profile cursor and publish through MQTT or HTTPS. If the uplink is down
the cursor simply stops advancing; on reconnect the backlog replays in order.
Device metrics are periodic live snapshots (their history already lives in
the monitor rollups, so they are not replayed).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Any

from .config import auth_headers_spec, cert_paths, gateway_id, https_url, load_config, save_config
from .publishers import HttpsPublisher, MqttPublisher, build_ssl_context
from .storage import ForwardingStorage


SENSOR_BATCH = 200
TOPIC_PREFIX = "metacrust"

_METRIC_SNAPSHOT_DROP = {"ok", "source", "message_id", "message_type", "received_at", "ipc", "stale_ms"}


def topics_for(gid: str) -> dict[str, str]:
    return {
        "status": f"{TOPIC_PREFIX}/{gid}/status",
        "sensors": f"{TOPIC_PREFIX}/{gid}/sensors/{{type}}/{{id}}",
        "device_metrics": f"{TOPIC_PREFIX}/{gid}/device/metrics",
        "device_anomalies": f"{TOPIC_PREFIX}/{gid}/device/anomalies",
    }


class ForwardingService:
    def __init__(
        self,
        core_ipc: Any | None = None,
        *,
        sensor_db_path: Path | str | None = None,
        monitor_db_path: Path | str | None = None,
    ) -> None:
        self.storage = ForwardingStorage()
        self.config = load_config()
        self.gateway_id = gateway_id()
        self.core_ipc = core_ipc
        self.sensor_db_path = Path(sensor_db_path) if sensor_db_path else _default_sensor_db()
        self.monitor_db_path = Path(monitor_db_path) if monitor_db_path else _default_monitor_db()
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._states: dict[str, dict[str, Any]] = {}

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        self.storage.open()
        for profile in self.config.get("profiles", []):
            if profile.get("enabled"):
                self._spawn(profile)

    async def stop(self) -> None:
        tasks = list(self._workers.values())
        self._workers.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self.storage.close()

    async def apply_config(self, config: dict[str, Any], pending_certs: dict[str, dict[str, str]] | None = None) -> None:
        save_config(config, pending_certs)
        self.config = config
        tasks = list(self._workers.values())
        self._workers.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        live_ids = set()
        for profile in config.get("profiles", []):
            live_ids.add(profile["id"])
            if profile.get("enabled"):
                self._spawn(profile)
        for pid in list(self._states):
            if pid not in live_ids:
                del self._states[pid]

    def _spawn(self, profile: dict[str, Any]) -> None:
        pid = profile["id"]
        self._states[pid] = {
            "state": "connecting",
            "last_error": None,
            "last_error_at_ms": None,
            "connected_since": 0,
            "publish_count": 0,
            "failed_count": 0,
            "last_publish_at_ms": None,
            "last_status_code": None,
            "replay_remaining": 0,
            "last_metrics_ms": 0,
            "pending_history": deque([0, 0, 0, 0, 0], maxlen=5),
        }
        self._workers[pid] = asyncio.create_task(self._worker(profile), name=f"forwarding-{pid}")

    # ── worker ───────────────────────────────────────────────────────────
    async def _worker(self, profile: dict[str, Any]) -> None:
        pid = profile["id"]
        state = self._states[pid]
        publisher: MqttPublisher | HttpsPublisher | None = None
        backoff = 5.0
        try:
            while True:
                try:
                    if publisher is None:
                        state["state"] = "connecting"
                        publisher = await asyncio.to_thread(self._build_publisher, profile)
                        state["state"] = "connected"
                        state["connected_since"] = _now_ms()
                        state["last_error"] = None
                        state["replay_remaining"] = self._pending(profile)
                        self.storage.add_event(pid, "info", "connected", self._destination(profile))
                        backoff = 5.0
                    busy = await self._pump_once(profile, publisher, state)
                    await asyncio.sleep(0.2 if busy else 1.0)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    was_connected = state["state"] == "connected"
                    state["state"] = "error"
                    state["last_error"] = str(exc)
                    state["last_error_at_ms"] = _now_ms()
                    state["failed_count"] += 1
                    self.storage.add_event(
                        pid, "error", "disconnected" if was_connected else "connect_failed", str(exc)
                    )
                    if publisher is not None:
                        await asyncio.to_thread(publisher.close)
                        publisher = None
                    await asyncio.sleep(backoff)
                    backoff = min(60.0, backoff * 2)
        finally:
            if publisher is not None:
                await asyncio.to_thread(publisher.close)

    def _build_publisher(self, profile: dict[str, Any]) -> MqttPublisher | HttpsPublisher:
        pid = profile["id"]
        certs = cert_paths(pid)
        if profile["protocol"] == "mqtt":
            m = profile.get("mqtt") or {}
            if not m.get("host"):
                raise RuntimeError("no broker host configured")
            context = None
            if m.get("tls"):
                context = build_ssl_context(
                    certs.get("tls_ca"),
                    certs.get("tls_cert") if m.get("mtls") else None,
                    certs.get("tls_key") if m.get("mtls") else None,
                )
            publisher = MqttPublisher(
                m["host"],
                int(m.get("port") or 1883),
                username=m.get("username", ""),
                password=m.get("password", ""),
                qos=int(m.get("qos", 1)),
                ssl_context=context,
                status_topic=topics_for(self.gateway_id)["status"],
                client_id=m.get("client_id") or f"{self.gateway_id}-{pid[:8]}",
            )
            publisher.connect()
            return publisher

        h = profile.get("https") or {}
        url = https_url(h)
        if not url:
            raise RuntimeError("no endpoint host configured")
        context = None
        if h.get("tls", True) and (certs.get("tls_ca") or h.get("mtls")):
            context = build_ssl_context(
                certs.get("tls_ca"),
                certs.get("tls_cert") if h.get("mtls") else None,
                certs.get("tls_key") if h.get("mtls") else None,
                verify=bool(h.get("verify_tls", True)),
            )
        return HttpsPublisher(
            url,
            mode=h.get("mode", "rest"),
            graphql_query=h.get("graphql_query", ""),
            auth=auth_headers_spec(h),
            ssl_context=context,
            verify_tls=bool(h.get("verify_tls", True)),
            gateway_id=self.gateway_id,
        )

    # ── one pump cycle: sensors → anomalies → metrics ────────────────────
    async def _pump_once(self, profile: dict[str, Any], publisher: Any, state: dict[str, Any]) -> bool:
        pid = profile["id"]
        sources = profile.get("sources") or {}
        topics = topics_for(self.gateway_id)
        busy = False

        wanted = sources.get("sensors") or []
        if wanted:
            rows = _tail(
                self.sensor_db_path,
                "SELECT id, ts_ms, source_type, source_id, ok, payload_json FROM sensor_messages WHERE id > ? ORDER BY id LIMIT ?",
                self.storage.get_cursor(pid, "sensors"),
                SENSOR_BATCH,
            )
            if rows:
                envelopes = []
                for row in rows:
                    key = f"{row['source_type']}:{row['source_id']}"
                    if wanted != "all" and key not in wanted:
                        continue
                    envelopes.append(self._sensor_envelope(row))
                if envelopes:
                    await self._deliver(publisher, profile, envelopes, topics, state)
                self.storage.set_cursor(pid, "sensors", int(rows[-1]["id"]))
                if envelopes:
                    self._count_delivery(pid, state, len(envelopes))
                    busy = True

        if sources.get("device_anomalies"):
            rows = _tail(
                self.monitor_db_path,
                "SELECT id, ts_ms, metric, metric_label, category, severity, value, z_score, delta_value,"
                " slope_value, warning_limit, critical_limit, alarm_name, headline, message"
                " FROM anomaly_events WHERE id > ? ORDER BY id LIMIT ?",
                self.storage.get_cursor(pid, "anomalies"),
                SENSOR_BATCH,
            )
            if rows:
                envelopes = [self._anomaly_envelope(row) for row in rows]
                await self._deliver(publisher, profile, envelopes, topics, state)
                self.storage.set_cursor(pid, "anomalies", int(rows[-1]["id"]))
                self._count_delivery(pid, state, len(envelopes))
                busy = True

        if sources.get("device_metrics") and self.core_ipc is not None:
            interval_ms = int(sources.get("metrics_interval_s", 5)) * 1000
            now = _now_ms()
            if now - state["last_metrics_ms"] >= interval_ms:
                snapshot = self.core_ipc.latest_device_metrics()
                if snapshot:
                    envelope = self._metrics_envelope(snapshot)
                    await self._deliver(publisher, profile, [envelope], topics, state)
                    state["last_metrics_ms"] = now
                    self._count_delivery(pid, state, 1, replayable=False)
                    busy = True

        state["pending_history"].append(self._pending(profile))
        return busy

    async def _deliver(
        self,
        publisher: Any,
        profile: dict[str, Any],
        envelopes: list[dict[str, Any]],
        topics: dict[str, str],
        state: dict[str, Any],
    ) -> None:
        if profile["protocol"] == "mqtt":
            def _publish_all() -> None:
                for envelope in envelopes:
                    publisher.publish(_mqtt_topic(topics, envelope), envelope)

            await asyncio.to_thread(_publish_all)
        else:
            await asyncio.to_thread(publisher.post, envelopes)
            state["last_status_code"] = getattr(publisher, "last_status_code", None)

    def _count_delivery(self, pid: str, state: dict[str, Any], count: int, *, replayable: bool = True) -> None:
        replayed = 0
        if replayable and state["replay_remaining"] > 0:
            replayed = min(count, state["replay_remaining"])
            state["replay_remaining"] -= replayed
        self.storage.bump(pid, sent=count - replayed, replayed=replayed)
        state["publish_count"] += count
        state["last_publish_at_ms"] = _now_ms()

    # ── envelopes ────────────────────────────────────────────────────────
    def _envelope(self, kind: str, source: dict[str, Any], ts_ms: int, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "gateway_id": self.gateway_id,
            "kind": kind,
            "source": source,
            "timestamp_ms": int(ts_ms),
            "data": data,
        }

    def _sensor_envelope(self, row: dict[str, Any]) -> dict[str, Any]:
        try:
            data = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            data = {"raw": row.get("payload_json")}
        return self._envelope(
            "sensor_data",
            {"type": row["source_type"], "id": row["source_id"]},
            row["ts_ms"],
            data,
        )

    def _anomaly_envelope(self, row: dict[str, Any]) -> dict[str, Any]:
        data = {k: row[k] for k in row.keys() if k not in ("id", "ts_ms") and row[k] is not None}
        return self._envelope(
            "anomaly_event",
            {"type": "device", "id": row.get("metric") or row.get("alarm_name") or "device"},
            row["ts_ms"],
            data,
        )

    def _metrics_envelope(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        data = {k: v for k, v in snapshot.items() if k not in _METRIC_SNAPSHOT_DROP}
        return self._envelope(
            "device_metrics",
            {"type": "device", "id": "metrics"},
            int(snapshot.get("timestamp_ms") or _now_ms()),
            data,
        )

    # ── introspection for the API layer ──────────────────────────────────
    def _pending(self, profile: dict[str, Any]) -> int:
        pid = profile["id"]
        sources = profile.get("sources") or {}
        pending = 0
        if sources.get("sensors"):
            pending += max(0, _max_id(self.sensor_db_path, "sensor_messages") - self.storage.get_cursor(pid, "sensors"))
        if sources.get("device_anomalies"):
            pending += max(0, _max_id(self.monitor_db_path, "anomaly_events") - self.storage.get_cursor(pid, "anomalies"))
        return pending

    def _destination(self, profile: dict[str, Any]) -> str:
        if profile["protocol"] == "mqtt":
            m = profile.get("mqtt") or {}
            return f"{m.get('host') or 'not-configured'}:{m.get('port') or 1883}"
        h = profile.get("https") or {}
        return h.get("url") or "not-configured"

    def status(self) -> dict[str, Any]:
        mqtt: list[dict[str, Any]] = []
        https: list[dict[str, Any]] = []
        for profile in self.config.get("profiles", []):
            if not profile.get("enabled"):
                continue
            pid = profile["id"]
            state = self._states.get(pid) or {}
            counters = self.storage.counters(pid)
            attempts = state.get("publish_count", 0) + state.get("failed_count", 0)
            buffer = {
                "pending": self._pending(profile),
                "replayed": counters["replayed"],
                "dropped": counters["dropped"],
                "success_rate": round(100 * state.get("publish_count", 0) / attempts) if attempts else 100,
            }
            common = {
                "profile_id": pid,
                "profile_name": profile.get("name", "Unnamed Profile"),
                "connected_since": state.get("connected_since", 0),
                "last_error": state.get("last_error"),
                "last_error_at_ms": state.get("last_error_at_ms"),
                "buffer": buffer,
            }
            if profile["protocol"] == "mqtt":
                m = profile.get("mqtt") or {}
                mqtt.append({
                    **common,
                    "state": state.get("state", "stopped"),
                    "broker": self._destination(profile),
                    "tls": bool(m.get("tls")),
                    "publish_count": state.get("publish_count", 0),
                    "last_publish_ago": _ago(state.get("last_publish_at_ms")),
                    "last_publish_at_ms": state.get("last_publish_at_ms"),
                })
            else:
                h = profile.get("https") or {}
                https.append({
                    **common,
                    "tunnel_alive": state.get("state") == "connected",
                    "endpoint": self._destination(profile),
                    "tls": bool(h.get("tls", True)),
                    "post_count": state.get("publish_count", 0),
                    "last_post_ago": _ago(state.get("last_publish_at_ms")),
                    "last_post_at_ms": state.get("last_publish_at_ms"),
                    "last_status_code": state.get("last_status_code"),
                })
        return {"ok": True, "mqtt": mqtt, "https": https, "timestamp_ms": _now_ms()}

    def buffer_stats(self) -> dict[str, Any]:
        profiles = []
        total_pending = total_replayed = total_dropped = 0
        rates = []
        for profile in self.config.get("profiles", []):
            pid = profile["id"]
            counters = self.storage.counters(pid)
            state = self._states.get(pid) or {}
            pending = self._pending(profile) if profile.get("enabled") else 0
            total_pending += pending
            total_replayed += counters["replayed"]
            total_dropped += counters["dropped"]
            attempts = state.get("publish_count", 0) + state.get("failed_count", 0)
            rates.append(100 * state.get("publish_count", 0) / attempts if attempts else 100)
            profiles.append({
                "profile_id": pid,
                "pending": pending,
                "replayed": counters["replayed"],
                "dropped": counters["dropped"],
                "history": list(state.get("pending_history") or [0, 0, 0, 0, 0]),
            })
        db_size_mb = 0.0
        for path in (self.sensor_db_path, self.monitor_db_path):
            try:
                db_size_mb += path.stat().st_size / (1024 * 1024)
            except OSError:
                pass
        return {
            "ok": True,
            "total_pending": total_pending,
            "total_replayed": total_replayed,
            "total_dropped": total_dropped,
            "success_rate": round(sum(rates) / len(rates)) if rates else 100,
            "profiles": profiles,
            "storage": {"db_size_mb": round(db_size_mb, 1), "estimated_capacity_mb": 0, "max_per_profile": 0},
        }

    def events(self, limit: int = 200) -> dict[str, Any]:
        names = {p["id"]: (p.get("name", "?"), p.get("protocol", "?")) for p in self.config.get("profiles", [])}
        events = []
        outages = recovered = errors = 0
        for row in self.storage.recent_events(limit):
            name, protocol = names.get(row["profile_id"], (row["profile_id"], "?"))
            if row["event"] == "connected":
                recovered += 1
            elif row["event"] == "disconnected":
                outages += 1
            if row["severity"] == "error":
                errors += 1
            events.append({
                "timestamp": row["ts_ms"],
                "profile": name,
                "protocol": protocol,
                "event": row["event"],
                "severity": row["severity"],
                "message": row["message"],
            })
        return {"ok": True, "events": events, "summary": {"outages": outages, "recovered": recovered, "errors": errors}}

    def seen_sensor_sources(self) -> list[dict[str, Any]]:
        rows = _query(
            self.sensor_db_path,
            "SELECT source_type, source_id, last_status, last_seen_ms FROM sensor_sources ORDER BY source_type, source_id",
        )
        return [
            {
                "key": f"{row['source_type']}:{row['source_id']}",
                "type": row["source_type"],
                "id": row["source_id"],
                "status": row["last_status"],
                "last_seen_ms": row["last_seen_ms"],
            }
            for row in rows
        ]


# ── module helpers ───────────────────────────────────────────────────────
def _default_sensor_db() -> Path:
    from gateway_interfaces.data_storage import GatewayInterfacesDataStorage

    return GatewayInterfacesDataStorage().db_path


def _default_monitor_db() -> Path:
    from gateway_ipc.monitor_storage import MonitorStorage

    return MonitorStorage().db_path


def _mqtt_topic(topics: dict[str, str], envelope: dict[str, Any]) -> str:
    kind = envelope.get("kind")
    if kind == "sensor_data":
        source = envelope.get("source") or {}
        return topics["sensors"].format(type=source.get("type", "unknown"), id=source.get("id", "unknown"))
    if kind == "anomaly_event":
        return topics["device_anomalies"]
    return topics["device_metrics"]


def _tail(db_path: Path, query: str, cursor_id: int, limit: int) -> list[dict[str, Any]]:
    return _query(db_path, query, (int(cursor_id), int(limit)))


def _query(db_path: Path, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        try:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def _max_id(db_path: Path, table: str) -> int:
    rows = _query(db_path, f"SELECT MAX(id) AS m FROM {table}")
    if rows and rows[0].get("m") is not None:
        return int(rows[0]["m"])
    return 0


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ago(ts_ms: int | None) -> str | None:
    if not ts_ms:
        return None
    seconds = max(0, int((_now_ms() - ts_ms) / 1000))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"
