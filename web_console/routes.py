from __future__ import annotations

import asyncio
import hashlib
import csv
import io
import json
import logging
import os
import secrets
import shutil
import subprocess
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from gateway_forwarding import (
    DEFAULT_GRAPHQL_QUERY,
    METRIC_INTERVAL_CHOICES,
    gateway_id as forwarding_gateway_id,
    load_config as load_forwarding_config,
    normalize_config as normalize_forwarding_config,
    save_config as persist_forwarding_config,
    topics_for as forwarding_topics_for,
)
from gateway_ipc import build_config_message, encode_message, headline_for_stored

from . import insights_data
from .network_runtime import RUNTIME as NETWORK_RUNTIME
from gateway_interfaces import GatewayInterfacesService, default_config


LOGGER = logging.getLogger("edge_server")
LOGGER.setLevel(logging.INFO)
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s edge_server %(message)s"))
    LOGGER.addHandler(_handler)
LOGGER.propagate = False

router = APIRouter()
PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))

# The same MAC-derived unit identity data forwarding publishes under, so the
# ID a customer sees on the Overview matches the one in their MQTT topics.
GATEWAY_ID = forwarding_gateway_id()
DEFAULT_USERNAME = "gateway"
DEFAULT_PASSWORD = "gateway"
EDGE_SERVER_CONFIG_PATH = Path(os.environ.get("GATEWAY_EDGE_SERVER_CONFIG_PATH", "/opt/metacrust/config/edge_server/config.json"))
INTERFACE_CONFIG_SECTIONS = ("rs232", "rs485", "modbus_tcp")
INTERFACES_SERVICE = GatewayInterfacesService()


def _file_hash(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()[:10]
    except Exception:
        return "dev"


templates.env.globals["js_hash"] = _file_hash(PACKAGE_DIR / "static" / "js" / "app.js")
templates.env.globals["css_hash"] = _file_hash(PACKAGE_DIR / "static" / "css" / "app.css")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def _json_auth_required(request: Request) -> JSONResponse | None:
    if _is_authenticated(request):
        return None
    return JSONResponse({"ok": False, "message": "Authentication required."}, status_code=status.HTTP_401_UNAUTHORIZED)


async def _send_config_to_core(request: Request, config_name: str, payload: dict[str, Any]) -> dict[str, object]:
    ipc = getattr(request.app.state, "core_ipc", None)
    return await _send_config_payload_to_core(ipc, config_name, payload)


async def _send_config_payload_to_core(ipc: object, config_name: str, payload: dict[str, Any]) -> dict[str, object]:
    message = build_config_message(config_name, payload, ack_required=True)
    result: dict[str, object] = {
        "sent": False,
        "message_id": message["message_id"],
        "message_type": message["message_type"],
    }

    if ipc is None:
        result["reason"] = "gateway core IPC task is not started"
        return result

    try:
        send_message = getattr(ipc, "send_message", None)
        if send_message is not None:
            reply = await send_message(message)
            result["acknowledged"] = reply is not None
        else:
            await ipc.send_text(encode_message(message))
    except Exception as exc:
        result["reason"] = str(exc)
        return result

    result["sent"] = True
    return result


def load_saved_sensor_configs() -> list[str]:
    try:
        config = INTERFACES_SERVICE.load()
    except Exception as exc:
        print(f"[gateway-interfaces] failed to load config: {exc}", flush=True)
        return []
    CONFIGS["rs232"] = INTERFACES_SERVICE.section("rs232")
    CONFIGS["rs485"] = INTERFACES_SERVICE.section("rs485")
    CONFIGS["modbus_tcp"] = INTERFACES_SERVICE.section("modbus_tcp")
    return ["rs232", "rs485", "modbus_tcp"]


def load_saved_edge_server_config() -> dict[str, Any]:
    try:
        loaded = _load_edge_server_config()
    except Exception as exc:
        LOGGER.exception("config_load failed error=%s", exc)
        loaded = None
    if loaded is not None:
        CONFIGS["edge_server"] = loaded
    return CONFIGS["edge_server"]


async def send_saved_sensor_configs_to_core(ipc: object, config_names: list[str] | None = None) -> list[dict[str, object]]:
    names = config_names or list(INTERFACE_CONFIG_SECTIONS)
    results: list[dict[str, object]] = []
    for config_name in names:
        results.append(await _send_config_payload_to_core(ipc, config_name, CONFIGS[config_name]))
    return results


def _primary_sections(active_label: str) -> list[dict[str, object]]:
    items = [
        ("Overview", "Over", "/dashboard"),
        ("Monitor", "Mon", "/monitor"),
        ("Insights", "Info", "/insights"),
        ("Interfaces", "I/O", "/interfaces"),
        ("Data Forwarding", "Fwd", "/forwarding"),
        ("Edge Server", "Srv", "/edge-server"),
        ("Connectivity", "Conn", "/connectivity"),
        ("System", "Sys", "/system"),
    ]
    return [
        {
            "label": label,
            "compact": compact,
            "href": href,
            "active": label == active_label,
            "disabled": False,
        }
        for label, compact, href in items
    ]


def _system_uptime() -> str:
    try:
        seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return "unknown"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _disk_usage() -> dict[str, object]:
    try:
        usage = shutil.disk_usage("/")
    except OSError:
        return {"pct": 0, "used_gb": 0, "total_gb": 0}
    used = usage.total - usage.free
    return {
        "pct": round(100 * used / usage.total) if usage.total else 0,
        "used_gb": round(used / 1024**3, 1),
        "total_gb": round(usage.total / 1024**3, 1),
    }


def _network_settings() -> dict[str, Any]:
    return {
        "version": 2,
        "network": {
            "defaults_behavior": {
                "create_defaults_if_missing": True,
                "restore_defaults_if_invalid": True,
                "backup_invalid_file": True,
            },
            "wifi_client": {
                "enabled": False,
                "interface": "wlan0",
                "auto_connect": True,
                "ssid": "",
                "hidden_ssid": False,
                "security": "wpa2-psk",
                "passphrase": "",
                "country_code": "",
                "band": "auto",
                "dhcp": True,
                "static_address": "",
                "static_gateway": "",
                "static_dns": [],
                "route_metric": 300,
            },
            "wifi_ap": {
                "enabled": False,
                "interface": "wlan0",
                "ssid": "Gateway-Setup",
                "security": "wpa2-psk",
                "passphrase": "",
                "country_code": "",
                "band": "2.4ghz",
                "channel": "auto",
                "channel_width": "20",
                "subnet_cidr": "192.168.50.1/24",
                "dhcp_server_enabled": True,
                "dhcp_range_start": "192.168.50.100",
                "dhcp_range_end": "192.168.50.180",
                "nat_enabled": True,
                "client_isolation": False,
                "shared_uplink_mode": "auto",
            },
            "cellular": {
                "enabled": False,
                "active_modem_id": "sim7600",
                "apn": "",
                "username": "",
                "password": "",
                "pin": "",
                "roaming_allowed": False,
                "modems": [{
                    "id": "sim7600",
                    "enabled": True,
                    "backend": "qmi",
                    "interface_type": "qmi",
                    "control_device": "/dev/cdc-wdm0",
                    "data_interface": "wwan0",
                    "route_metric": 500,
                    "ip_type": "4",
                }],
            },
            "uplink": {
                "uplink_priority": ["eth0", "eth1", "wifi_client", "cellular"],
                "failback_enabled": True,
                "stable_seconds_before_switch": 0,
                "require_connectivity_check": True,
                "fail_count_threshold": 1,
                "recover_count_threshold": 1,
                "connectivity_targets": ["1.1.1.1", "8.8.8.8"],
            },
        },
    }


def _network_state() -> dict[str, Any]:
    now = _now_ms()
    return {
        "active_uplink": "none",
        "monitor_status": "v2_shell",
        "recovery": {"count": 0, "last_reason": "", "last_timestamp": ""},
        "tailscale_recovery": {"count": 0, "last_reason": "", "last_timestamp": ""},
        "eth0": {"link_up": False, "interface_up": False, "address": "", "internet_ok": False},
        "eth1": {"link_up": False, "interface_up": False, "address": "", "internet_ok": False},
        "wifi_client": {
            "interface": "wlan0",
            "enabled": False,
            "present": True,
            "link_up": False,
            "interface_up": False,
            "address": "",
            "connected_ssid": "",
            "configured_ssid": "",
            "internet_ok": False,
            "diagnostics": {"reason": "disabled"},
        },
        "wifi_ap": {"interface": "wlan0", "enabled": False, "address": "", "clients": 0},
        "cellular": {
            "enabled": False,
            "present": False,
            "connected": False,
            "sim_status": "unknown",
            "operator": "",
            "signal_percent": None,
            "signal_dbm": None,
        },
        "uplink_stats": {
            "network": {"has_uplink": False, "internet_ok": False, "reason": "C++ engine not connected yet"},
            "interfaces": {},
        },
        "_audit": {
            "active_uplink_since_ms": now,
            "active_duration_ms": 0,
            "open_outage": None,
            "switch_count": 0,
            "last_outage": None,
        },
        "last_apply_status": "not_applied",
        "last_apply_timestamp": _iso_now(),
    }


def _apply_result() -> dict[str, Any]:
    return {
        "ok": True,
        "status": "not_applied",
        "timestamp": _iso_now(),
        "config_generation": 1,
        "used_defaults": True,
        "active_uplink": "none",
        "errors": [],
        "warnings": [{"scope": "gateway_hub", "code": "mock", "message": "Using v2 shell mock data."}],
    }


def _overview_status_payload(network_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status_chips": [
            {"label": "Gateway", "value": "Standby"},
            {"label": "Primary Link", "value": "Offline"},
            {"label": "Wireless", "value": "Standby"},
            {"label": "Cellular", "value": "Disabled"},
        ],
        "connectivity_items": [
            {"label": "Ethernet", "state": "Disconnected", "detail": "No cable link", "tone": "inactive"},
            {"label": "Wi-Fi", "state": "Standby", "detail": "Radio available for setup", "tone": "standby"},
            {"label": "Cellular", "state": "Disabled", "detail": "Cellular fallback is off", "tone": "inactive"},
            {"label": "Data Forwarding", "state": "Idle", "detail": "No profiles configured", "tone": "standby"},
        ],
        "visual": {
            "gateway_online": False,
            "ethernet_active": False,
            "wifi_active": False,
            "cellular_active": False,
        },
    }


# Charts shown on the Monitor > Anomalies tab. `metric` matches the C++
# metricName so stored series and anomaly overlays line up. `safe_limit` /
# `crit_limit` are the warning + critical thresholds the engine uses today
# (rules are hard-coded in gateway_core); they are display-only, used to draw
# the coloured safe/warning/critical zones and the at-a-glance status.
MONITOR_CHARTS = [
    {"metric": "cpu.usage", "label": "CPU Usage", "unit": "%", "min": 0, "max": 100, "safe_limit": 85, "crit_limit": 95,
     "plain": "How hard the processor is working."},
    {"metric": "cpu.temp", "label": "CPU Temperature", "unit": "°C", "min": 0, "max": 100, "safe_limit": 75, "crit_limit": 85,
     "plain": "How hot the processor is running."},
    {"metric": "memory.ram_used_pct", "label": "Memory Usage", "unit": "%", "min": 0, "max": 100, "safe_limit": 80, "crit_limit": 90,
     "plain": "How much working memory is in use."},
    {"metric": "storage.disk_used_pct", "label": "System Storage", "unit": "%", "min": 0, "max": 100, "safe_limit": 80, "crit_limit": 90,
     "plain": "How full the main system storage is."},
    {"metric": "storage.emmc_used_pct", "label": "Disk (eMMC) Usage", "unit": "%", "min": 0, "max": 100, "safe_limit": 80, "crit_limit": 90,
     "plain": "How full the device's flash storage is."},
    {"metric": "cpu.load_1m", "label": "System Load", "unit": "", "min": 0, "max": 2, "safe_limit": 0.9, "crit_limit": 1.5,
     "plain": "Overall demand on the device right now."},
]

# Plain-English description of what the anomaly engine does, for the Overview
# page. Deliberately avoids jargon (no "z-score", "delta", etc.).
# `category` matches the value stored on each anomaly event (see
# message_protocol._DETECTOR_CATEGORY) so the UI can show a live count per kind.
ANOMALY_ENGINE_CHECKS = [
    {"category": "Crossed a safe limit", "title": "Crosses a safe limit", "detail": "A value goes past a level you consider healthy, such as a temperature getting too high."},
    {"category": "Sudden spike", "title": "Spikes suddenly", "detail": "A value jumps sharply in a moment instead of changing gradually."},
    {"category": "Rising quickly", "title": "Climbs too fast", "detail": "A value keeps rising quickly, hinting at a leak or runaway trend."},
    {"category": "Behaving unusually vs normal", "title": "Behaves unusually", "detail": "A value drifts away from its own normal pattern."},
    {"category": "Sensor stopped reporting", "title": "Goes quiet", "detail": "A signal stops reporting, so we flag the blind spot."},
    {"category": "Reading looks invalid", "title": "Looks invalid", "detail": "A reading is impossible or out of range, pointing to a faulty source."},
]

# Plain-language summary of the rules currently active on the device. Rules are
# hard-coded in gateway_core today; a future release lets users define their own
# per metric / per sensor. Display-only.
ANOMALY_RULES = [
    {"label": "CPU Usage", "watches": "How hard the processor is working",
     "rule": "Flagged when usage stays above 85% (warning) or 95% (critical). Sudden spikes and unusual behaviour are flagged too."},
    {"label": "CPU Temperature", "watches": "How hot the processor is running",
     "rule": "Flagged above 75 °C (warning) or 85 °C (critical). Sudden jumps and fast-rising temperature are flagged too."},
    {"label": "Memory Usage", "watches": "How much working memory is in use",
     "rule": "Flagged above 80% (warning) or 90% (critical). Sudden jumps and a steady climb (possible leak) are flagged too."},
    {"label": "System Storage", "watches": "How full the main storage is",
     "rule": "Flagged above 80% (warning) or 90% (critical). Storage that fills up quickly is flagged too."},
    {"label": "Disk (eMMC) Usage", "watches": "How full the device's flash storage is",
     "rule": "Flagged above 80% (warning) or 90% (critical). Fast-filling storage is flagged too."},
    {"label": "System Load", "watches": "Overall demand on the device",
     "rule": "Flagged when demand stays above 0.9 (warning) or 1.5 (critical) per processor core, or looks unusual."},
]


def _monitor_chart_catalog() -> list[dict[str, Any]]:
    return [dict(chart) for chart in MONITOR_CHARTS]


def _system_metrics(core_ipc: Any | None = None) -> dict[str, Any]:
    if core_ipc is not None:
        latest = core_ipc.latest_device_metrics()
        if latest:
            payload = dict(latest)
            payload["ipc"] = core_ipc.snapshot()
            payload["stale_ms"] = max(0, _now_ms() - int(payload.get("timestamp_ms") or _now_ms()))
            return payload
    now = _now_ms()
    return {
        "ok": True,
        "source": "unavailable",
        "timestamp_ms": now,
        "cpu": {
            "total_percent": 0,
            "core_count": 4,
            "per_core": [{"core": i, "usage_percent": 0, "freq_mhz": 0} for i in range(4)],
            "load_average": {"1m": 0, "5m": 0, "15m": 0},
            "throttle_flags": 0,
        },
        "memory": {"memory_bytes": {"used_percent": 0, "used": 0, "total": 0}, "swap_mb": {"used": 0}},
        "temperature_c": None,
        "filesystem": {"used_percent": 0, "label": "root filesystem"},
        "emmc": {"used_percent": 0, "used_mb": 0, "total_mb": 0, "life_used_percent": 0},
        "uptime_sec": 0,
        "ipc": core_ipc.snapshot() if core_ipc is not None else None,
    }


def _system_metric_history(core_ipc: Any | None = None) -> dict[str, Any]:
    if core_ipc is not None:
        samples = core_ipc.device_metric_history()
        if len(samples) >= 2:
            return {"ok": True, "source": "gateway_core_ipc", "samples": samples}
    samples = []
    now = _now_ms()
    for i in range(30, 0, -1):
        samples.append({
            "timestamp_ms": now - i * 10_000,
            "cpu_total_percent": 0,
            "memory_used_percent": 0,
            "temperature_c": 0,
            "disk_used_percent": 0,
            "emmc_used_percent": 0,
            "load_avg_1m": 0,
        })
    return {"ok": True, "source": "unavailable", "samples": samples}


def _default_rs232_config() -> dict[str, Any]:
    base_port = {
        "enabled": False,
        "serial": {"baud_rate": 9600, "data_bits": 8, "parity": "none", "stop_bits": 1},
        "sensor": "dustrak",
        "dustrak": {
            "polling": {
                "read_identity_on_init": True,
                "poll_status": True,
                "auto_start_measurement": False,
                "poll_measurements": True,
                "poll_measurement_stats": False,
                "poll_fault_messages": False,
                "poll_alarm_messages": False,
                "poll_log_info": False,
            },
            "driver": {"update_ram_after_write": True},
            "alarms": {
                key: {
                    "alarm1_state": "off",
                    "alarm1_mg_per_m3": 0.0,
                    "stel_alarm1_enabled": False,
                    "alarm2_state": "off",
                    "alarm2_mg_per_m3": 0.0,
                }
                for key in ("pm1", "pm25", "pm4", "pm10", "total")
            },
            "analog_output": {
                "state": "off",
                "channel": None,
                "min_mg_per_m3": 0.0,
                "max_mg_per_m3": 1.0,
            },
        },
    }
    return {"version": 1, "rs232": {"port_0": dict(base_port), "port_1": dict(base_port)}}


def _default_rs485_config() -> dict[str, Any]:
    base_port = {
        "enabled": False,
        "serial": {"baud_rate": 9600, "data_bits": 8, "parity": "none", "stop_bits": 1},
        "modbus_rtu": {"slave_address": 1, "poll_interval_ms": 1000, "registers": []},
    }
    return {"version": 1, "rs485": {"port_2": dict(base_port), "port_3": dict(base_port)}}


def _default_modbus_tcp_config() -> dict[str, Any]:
    return {"version": 1, "max_connections": 10, "connections": []}


def _default_edge_server_config() -> dict[str, Any]:
    return {
        "version": 1,
        "listeners": {
            "bind_mode": "interfaces",
            "bind_interfaces": ["eth0", "eth1", "wlan0", "wwan0", "tailscale0"],
            "http": {"enabled": False, "port": 8080},
            "https": {"enabled": False, "port": 8443, "tls_mode": "server", "mtls_required": False},
            "mqtt": {"enabled": False, "port": 1883, "allow_anonymous": False},
            "mqtts": {"enabled": False, "port": 8883, "tls_mode": "server", "mtls_required": False},
        },
        "funnel": {
            "enabled": False,
            "http": True,
            "https": False,
            "mqtt": False,
            "mqtts": False,
        },
        "http_endpoints": [],
        "mqtt_topics": [],
        "storage": {"enabled": True, "retention_days": 30, "max_size_mb": 5120},
        "tls": {
            "use_secrets": True,
            "secrets_dir": "/opt/metacrust/secrets/edge_server",
            "server_cert": "server.crt",
            "server_key": "server.key",
            "client_ca": "client-ca.crt",
        },
    }


_INTERFACE_DEFAULTS = default_config()
CONFIGS: dict[str, dict[str, Any]] = {
    "network": NETWORK_RUNTIME.load_settings() or _network_settings(),
    "rs232": {"version": 1, "rs232": _INTERFACE_DEFAULTS["rs232"]},
    "rs485": {"version": 1, "rs485": _INTERFACE_DEFAULTS["rs485"]},
    "modbus_tcp": {"version": 1, **_INTERFACE_DEFAULTS["modbus_tcp"]},
    "forwarding": load_forwarding_config(),
    "edge_server": _default_edge_server_config(),
}

ALERT_RULES, NEXT_RULE_ID = insights_data.load_alert_rules()
INSIGHTS_EVENTS = insights_data.AlertEventStore()


def _forwarding_available_sources(request: Request) -> list[dict[str, Any]]:
    """Sensor sources the user can pick in 'What to send' — the live list the
    C++ runtimes have actually reported (authoritative source_type/source_id)."""
    service = getattr(request.app.state, "forwarding", None)
    if service is None:
        return []
    try:
        return service.seen_sensor_sources()
    except Exception as exc:
        LOGGER.warning("forwarding_sources_failed error=%s", exc)
        return []


def _normalise_edge_server_config(payload: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_edge_server_config()
    raw_listeners = dict(payload.get("listeners") or {})
    listeners = dict(defaults["listeners"])
    listeners["bind_mode"] = str(raw_listeners.get("bind_mode") or listeners["bind_mode"])
    if listeners["bind_mode"] not in {"interfaces", "local", "all", "tailscale"}:
        listeners["bind_mode"] = "interfaces"
    allowed_interfaces = {"eth0", "eth1", "wlan0", "wwan0", "tailscale0"}
    raw_bind_interfaces = raw_listeners.get("bind_interfaces")
    if isinstance(raw_bind_interfaces, list):
        bind_interfaces = [
            str(item)
            for item in raw_bind_interfaces
            if str(item) in allowed_interfaces
        ]
    else:
        bind_interfaces = list(defaults["listeners"]["bind_interfaces"])
    listeners["bind_interfaces"] = bind_interfaces
    listeners["bind_mode"] = "interfaces"

    for key in ("http", "https", "mqtt", "mqtts"):
        item = dict(listeners[key])
        item.update(dict(raw_listeners.get(key) or {}))
        item["enabled"] = _bool_config(item.get("enabled"), False)
        item["port"] = max(1, min(65535, int(item.get("port") or listeners[key]["port"])))
        if key in {"https", "mqtts"}:
            item["mtls_required"] = _bool_config(item.get("mtls_required"), False)
            item["tls_mode"] = str(item.get("tls_mode") or "server")
        if key == "mqtt":
            item["allow_anonymous"] = _bool_config(item.get("allow_anonymous"), False)
        listeners[key] = item

    http_endpoints = []
    for raw in payload.get("http_endpoints") or []:
        if not isinstance(raw, dict):
            continue
        endpoint = dict(raw)
        endpoint["id"] = str(endpoint.get("id") or secrets.token_hex(8))[:32]
        endpoint["name"] = str(endpoint.get("name") or "HTTP Endpoint")[:64]
        endpoint["enabled"] = _bool_config(endpoint.get("enabled"), True)
        endpoint["protocol"] = str(endpoint.get("protocol") or "http")
        if endpoint["protocol"] not in {"http", "https"}:
            endpoint["protocol"] = "http"
        endpoint["method"] = str(endpoint.get("method") or "POST").upper()
        endpoint["path"] = str(endpoint.get("path") or "/ingest")[:160]
        endpoint["auth"] = str(endpoint.get("auth") or "token")
        endpoint["payload_type"] = str(endpoint.get("payload_type") or "json")
        endpoint["device_id_source"] = str(endpoint.get("device_id_source") or "payload")
        endpoint["device_id_key"] = str(endpoint.get("device_id_key") or "device_id")[:80]
        endpoint["forwarding_profile"] = str(endpoint.get("forwarding_profile") or "store_only")
        http_endpoints.append(endpoint)

    mqtt_topics = []
    for raw in payload.get("mqtt_topics") or []:
        if not isinstance(raw, dict):
            continue
        topic = dict(raw)
        topic["id"] = str(topic.get("id") or secrets.token_hex(8))[:32]
        topic["name"] = str(topic.get("name") or "MQTT Topic")[:64]
        topic["enabled"] = _bool_config(topic.get("enabled"), True)
        topic["protocol"] = str(topic.get("protocol") or "mqtt")
        if topic["protocol"] not in {"mqtt", "mqtts"}:
            topic["protocol"] = "mqtt"
        topic["topic_filter"] = str(topic.get("topic_filter") or "devices/+/data")[:180]
        topic["qos"] = max(0, min(2, int(topic.get("qos") or 0)))
        topic["payload_type"] = str(topic.get("payload_type") or "json")
        topic["device_id_source"] = str(topic.get("device_id_source") or "topic_segment")
        topic["device_id_key"] = str(topic.get("device_id_key") or "1")[:80]
        topic["forwarding_profile"] = str(topic.get("forwarding_profile") or "store_only")
        mqtt_topics.append(topic)

    raw_storage = dict(payload.get("storage") or {})
    storage = dict(defaults["storage"])
    storage.update(raw_storage)
    storage["enabled"] = _bool_config(storage.get("enabled"), True)
    storage["retention_days"] = max(1, min(3650, int(storage.get("retention_days") or 30)))
    storage["max_size_mb"] = max(5120, min(1_048_576, int(storage.get("max_size_mb") or 5120)))

    raw_tls = dict(payload.get("tls") or {})
    tls = dict(defaults["tls"])
    tls.update(raw_tls)
    tls["use_secrets"] = _bool_config(tls.get("use_secrets"), True)
    tls["secrets_dir"] = str(tls.get("secrets_dir") or defaults["tls"]["secrets_dir"])[:180]
    tls["server_cert"] = str(tls.get("server_cert") or defaults["tls"]["server_cert"])[:120]
    tls["server_key"] = str(tls.get("server_key") or defaults["tls"]["server_key"])[:120]
    tls["client_ca"] = str(tls.get("client_ca") or defaults["tls"]["client_ca"])[:120]

    raw_funnel = dict(payload.get("funnel") or {})
    funnel = dict(defaults["funnel"])
    funnel.update(raw_funnel)
    funnel["enabled"] = _bool_config(funnel.get("enabled"), False)
    for key in ("http", "https", "mqtt", "mqtts"):
        funnel[key] = _bool_config(funnel.get(key), defaults["funnel"][key])

    return {
        "version": 1,
        "listeners": listeners,
        "funnel": funnel,
        "http_endpoints": http_endpoints[:32],
        "mqtt_topics": mqtt_topics[:32],
        "storage": storage,
        "tls": tls,
    }


def _bool_config(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _edge_server_public_config(config: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(config)
    payload["tls"] = {"managed": True, "installed": _edge_server_tls_status(config)}
    return payload


def _tailscale_hostname() -> str:
    env_host = os.environ.get("METACRUST_FUNNEL_HOST", "").strip().strip(".")
    if env_host:
        return env_host
    try:
        completed = subprocess.run(
            ["tailscale", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
        if completed.returncode == 0:
            payload = json.loads(completed.stdout or "{}")
            name = str(((payload.get("Self") or {}).get("DNSName")) or "").strip().strip(".")
            if name:
                return name
    except Exception as exc:
        LOGGER.error("funnel_hostname_lookup_failed error=%s", exc)
    return ""


def _tailscale_funnel_raw_status() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["tailscale", "funnel", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
        if completed.returncode == 0:
            return json.loads(completed.stdout or "{}")
        LOGGER.error("funnel_status_failed stderr=%s", completed.stderr.strip())
    except FileNotFoundError:
        LOGGER.error("funnel_status_failed tailscale_not_installed")
    except Exception as exc:
        LOGGER.error("funnel_status_failed error=%s", exc)
    return {}


def _funnel_allocations(config: dict[str, Any]) -> list[dict[str, Any]]:
    config = _normalise_edge_server_config(config)
    funnel = dict(config.get("funnel") or {})
    listeners = dict(config.get("listeners") or {})
    host = _tailscale_hostname()
    allocations: list[dict[str, Any]] = []

    def listener_port(name: str, fallback: int) -> int:
        return int((listeners.get(name) or {}).get("port") or fallback)

    def listener_enabled(name: str) -> bool:
        return bool((listeners.get(name) or {}).get("enabled"))

    if funnel.get("http"):
        allocations.append({
            "service": "http",
            "label": "HTTP endpoints",
            "enabled": bool(funnel.get("enabled")) and listener_enabled("http"),
            "available": listener_enabled("http"),
            "reason": "" if listener_enabled("http") else "HTTP listener is off",
            "public_port": 443,
            "public_url": f"https://{host}" if host else "",
            "target": f"http://127.0.0.1:{listener_port('http', 8080)}",
            "command": ["tailscale", "funnel", "--bg", "--yes", "--https=443", f"http://127.0.0.1:{listener_port('http', 8080)}"],
            "off_command": ["tailscale", "funnel", "--https=443", "off"],
        })

    tcp_ports = [8443, 10000]

    def take_tcp_port(preferred: int | None = None) -> int | None:
        if preferred in tcp_ports:
            tcp_ports.remove(preferred)
            return preferred
        if tcp_ports:
            return tcp_ports.pop(0)
        return None

    if funnel.get("https"):
        public_port = take_tcp_port(8443)
        allocations.append({
            "service": "https",
            "label": "HTTPS passthrough",
            "enabled": bool(funnel.get("enabled")) and listener_enabled("https") and public_port is not None,
            "available": listener_enabled("https") and public_port is not None,
            "reason": "" if listener_enabled("https") and public_port is not None else "HTTPS listener is off or no Funnel TCP port is free",
            "public_port": public_port,
            "public_url": f"https://{host}:{public_port}" if host and public_port else "",
            "target": f"tcp://127.0.0.1:{listener_port('https', 8443)}",
            "command": ["tailscale", "funnel", "--bg", "--yes", f"--tcp={public_port}", f"tcp://127.0.0.1:{listener_port('https', 8443)}"] if public_port else [],
            "off_command": ["tailscale", "funnel", f"--tcp={public_port}", "off"] if public_port else [],
        })

    if funnel.get("mqtt"):
        public_port = take_tcp_port(10000)
        allocations.append({
            "service": "mqtt",
            "label": "MQTT",
            "enabled": bool(funnel.get("enabled")) and listener_enabled("mqtt") and public_port is not None,
            "available": listener_enabled("mqtt") and public_port is not None,
            "reason": "" if listener_enabled("mqtt") and public_port is not None else "MQTT listener is off or no Funnel TCP port is free",
            "public_port": public_port,
            "public_url": f"mqtt://{host}:{public_port}" if host and public_port else "",
            "target": f"tcp://127.0.0.1:{listener_port('mqtt', 1883)}",
            "command": ["tailscale", "funnel", "--bg", "--yes", f"--tcp={public_port}", f"tcp://127.0.0.1:{listener_port('mqtt', 1883)}"] if public_port else [],
            "off_command": ["tailscale", "funnel", f"--tcp={public_port}", "off"] if public_port else [],
        })

    if funnel.get("mqtts"):
        public_port = take_tcp_port(10000)
        allocations.append({
            "service": "mqtts",
            "label": "MQTTS",
            "enabled": bool(funnel.get("enabled")) and listener_enabled("mqtts") and public_port is not None,
            "available": listener_enabled("mqtts") and public_port is not None,
            "reason": "" if listener_enabled("mqtts") and public_port is not None else "MQTTS listener is off or no Funnel TCP port is free",
            "public_port": public_port,
            "public_url": f"mqtts://{host}:{public_port}" if host and public_port else "",
            "target": f"tcp://127.0.0.1:{listener_port('mqtts', 8883)}",
            "command": ["tailscale", "funnel", "--bg", "--yes", f"--tcp={public_port}", f"tcp://127.0.0.1:{listener_port('mqtts', 8883)}"] if public_port else [],
            "off_command": ["tailscale", "funnel", f"--tcp={public_port}", "off"] if public_port else [],
        })

    return allocations


def _edge_server_funnel_status(config: dict[str, Any]) -> dict[str, Any]:
    config = _normalise_edge_server_config(config)
    funnel = dict(config.get("funnel") or {})
    allocations = _funnel_allocations(config)
    return {
        "ok": True,
        "hostname": _tailscale_hostname(),
        "enabled": bool(funnel.get("enabled")),
        "config": funnel,
        "services": [
            {
                key: value
                for key, value in item.items()
                if key not in {"command", "off_command"}
            }
            for item in allocations
        ],
        "raw_status": _tailscale_funnel_raw_status(),
    }


def _run_funnel_command(command: list[str]) -> None:
    if not command:
        return
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=12)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "tailscale funnel command failed")


def _apply_edge_server_funnel(config: dict[str, Any]) -> None:
    allocations = _funnel_allocations(config)
    for command in (
        ["tailscale", "funnel", "--https=443", "off"],
        ["tailscale", "funnel", "--tcp=8443", "off"],
        ["tailscale", "funnel", "--tcp=10000", "off"],
    ):
        try:
            _run_funnel_command(command)
        except Exception as exc:
            LOGGER.info("funnel_off_skip command=%s error=%s", " ".join(command), exc)

    funnel = _normalise_edge_server_config(config).get("funnel") or {}
    if not funnel.get("enabled"):
        return
    for item in allocations:
        if not item.get("enabled"):
            continue
        command = list(item.get("command") or [])
        _run_funnel_command(command)
        LOGGER.info(
            "funnel_enabled service=%s public=%s target=%s",
            item.get("service"),
            item.get("public_url"),
            item.get("target"),
        )


def _edge_server_tls_paths(config: dict[str, Any]) -> dict[str, Path]:
    tls = dict((_normalise_edge_server_config(config)).get("tls") or {})
    cert_dir = Path(str(tls.get("secrets_dir") or "/opt/metacrust/secrets/edge_server"))
    return {
        "server_cert": cert_dir / str(tls.get("server_cert") or "server.crt"),
        "server_key": cert_dir / str(tls.get("server_key") or "server.key"),
        "client_ca": cert_dir / str(tls.get("client_ca") or "client-ca.crt"),
    }


def _edge_server_tls_status(config: dict[str, Any]) -> dict[str, bool]:
    paths = _edge_server_tls_paths(config)
    status_map: dict[str, bool] = {}
    for name, path in paths.items():
        try:
            status_map[name] = path.exists() and path.stat().st_size > 0
        except OSError:
            status_map[name] = False
    return status_map


def _validate_pem(name: str, value: str) -> str:
    pem = value.strip()
    if not pem:
        return ""
    if name == "server_key":
        valid = "-----BEGIN" in pem and "PRIVATE KEY-----" in pem and "-----END" in pem
    else:
        valid = "-----BEGIN CERTIFICATE-----" in pem and "-----END CERTIFICATE-----" in pem
    if not valid:
        raise ValueError(f"Invalid {name.replace('_', ' ')} PEM.")
    return pem + "\n"


def _save_edge_server_tls(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, bool]:
    paths = _edge_server_tls_paths(config)
    paths["server_cert"].parent.mkdir(parents=True, exist_ok=True)
    paths["server_cert"].parent.chmod(0o700)
    for name, path in paths.items():
        pem = _validate_pem(name, str(payload.get(name) or ""))
        if not pem:
            continue
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(pem, encoding="utf-8")
        tmp_path.chmod(0o600)
        tmp_path.replace(path)
        path.chmod(0o600)
    return _edge_server_tls_status(config)


def _save_edge_server_config(payload: dict[str, Any]) -> dict[str, object]:
    EDGE_SERVER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = EDGE_SERVER_CONFIG_PATH.with_suffix(EDGE_SERVER_CONFIG_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(EDGE_SERVER_CONFIG_PATH)
    return {"saved": True, "path": str(EDGE_SERVER_CONFIG_PATH)}


def _load_edge_server_config() -> dict[str, Any] | None:
    if not EDGE_SERVER_CONFIG_PATH.exists():
        return None
    payload = json.loads(EDGE_SERVER_CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid Edge Server config in {EDGE_SERVER_CONFIG_PATH}")
    return _normalise_edge_server_config(payload)


def _edge_export_filters(request: Request) -> dict[str, Any]:
    query = request.query_params
    return {
        "protocol": query.get("protocol"),
        "protocol_group": query.get("protocol_group"),
        "device_id": query.get("device_id"),
        "route": query.get("route"),
        "event_type": query.get("event_type"),
        "severity": query.get("severity"),
        "payload_type": query.get("payload_type"),
        "accepted": query.get("accepted"),
        "from": query.get("from"),
        "to": query.get("to"),
        "limit": query.get("limit") or 1000,
        "include_payload": query.get("include_payload"),
    }


def _edge_export_rows(request: Request, export_type: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is None:
        return []
    active_filters = filters or _edge_export_filters(request)
    if export_type == "messages":
        return edge_server.export_messages(active_filters)
    return edge_server.export_events(active_filters)


def _csv_download(filename: str, rows: list[dict[str, Any]], fields: list[str]) -> Response:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _export_cell(row.get(field)) for field in fields})
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _jsonl_download(filename: str, rows: list[dict[str, Any]]) -> Response:
    lines = [
        json.dumps(_export_json_row(row), separators=(",", ":"), ensure_ascii=False)
        for row in rows
    ]
    return Response(
        "\n".join(lines) + ("\n" if lines else ""),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _export_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _export_json_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _export_json_value(value) for key, value in row.items()}


def _export_json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    return value


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "include"}


def _forwarding_status() -> dict[str, Any]:
    mqtt = []
    https = []
    for profile in CONFIGS["forwarding"].get("profiles", []):
        if not profile.get("enabled"):
            continue
        pid = profile.get("id", "")
        if profile.get("protocol") == "mqtt":
            m = profile.get("mqtt") or {}
            mqtt.append({
                "profile_id": pid,
                "profile_name": profile.get("name", "Unnamed Profile"),
                "state": "stopped",
                "broker": f"{m.get('host') or 'not-configured'}:{m.get('port') or 1883}",
                "tls": bool(m.get("tls")),
                "publish_count": 0,
                "connected_since": 0,
                "last_publish_ago": None,
                "last_publish_at_ms": None,
                "last_error": "C++/hub forwarding service not connected yet",
                "last_error_at_ms": _now_ms(),
                "buffer": {"pending": 0, "replayed": 0, "dropped": 0, "success_rate": 100},
            })
        else:
            h = profile.get("https") or {}
            scheme = "https" if h.get("tls", True) else "http"
            https.append({
                "profile_id": pid,
                "profile_name": profile.get("name", "Unnamed Profile"),
                "tunnel_alive": False,
                "endpoint": f"{scheme}://{h.get('host') or 'not-configured'}:{h.get('port') or 443}",
                "tls": bool(h.get("tls", True)),
                "post_count": 0,
                "connected_since": 0,
                "last_post_ago": None,
                "last_post_at_ms": None,
                "last_error": "C++/hub forwarding service not connected yet",
                "last_error_at_ms": _now_ms(),
                "last_status_code": None,
                "buffer": {"pending": 0, "replayed": 0, "dropped": 0, "success_rate": 100},
            })
    return {"ok": True, "mqtt": mqtt, "https": https, "timestamp_ms": _now_ms()}


def _edge_server_status() -> dict[str, Any]:
    config = CONFIGS["edge_server"]
    listeners = config.get("listeners", {})
    http_count = sum(1 for item in config.get("http_endpoints", []) if item.get("enabled"))
    mqtt_count = sum(1 for item in config.get("mqtt_topics", []) if item.get("enabled"))
    enabled_services = [
        name.upper()
        for name in ("http", "https", "mqtt", "mqtts")
        if listeners.get(name, {}).get("enabled")
    ]
    return {
        "ok": True,
        "state": "configured" if enabled_services else "standby",
        "services": enabled_services,
        "active_http_endpoints": http_count,
        "active_mqtt_topics": mqtt_count,
        "stored_records": 0,
        "pending_forward": 0,
        "connected_devices": 0,
        "buffer": {
            "pending": 0,
            "processed": 0,
            "forwarded": 0,
            "dropped": 0,
        },
        "devices": [],
        "audit": {
            "total": 0,
            "outages": 0,
            "errors": 0,
            "auth_failures": 0,
            "events": [],
        },
        "last_received_at": None,
        "tailscale_reachable": listeners.get("bind_mode") == "tailscale",
        "message": "Configuration ready",
        "timestamp_ms": _now_ms(),
    }


def _edge_server_window_minutes(request: Request) -> int:
    try:
        return max(5, min(1440, int(request.query_params.get("minutes") or 60)))
    except (TypeError, ValueError):
        return 60


def _template_context(active: str, page_title: str) -> dict[str, Any]:
    return {
        "product_name": "MetaCrust Edge Gateway",
        "page_title": page_title,
        "primary_sections": _primary_sections(active),
    }


@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if _is_authenticated(request):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", _template_context("", "Login"))


@router.head("/", response_class=HTMLResponse)
async def login_page_head() -> HTMLResponse:
    return HTMLResponse("")


@router.post("/api/login")
async def login_action(request: Request) -> JSONResponse:
    payload = await request.json()
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    if username == DEFAULT_USERNAME and password == DEFAULT_PASSWORD:
        request.session["authenticated"] = True
        request.session["username"] = username
        return JSONResponse({"ok": True, "redirect": "/dashboard"})
    return JSONResponse({"ok": False, "message": "Invalid credentials."}, status_code=status.HTTP_401_UNAUTHORIZED)


@router.post("/logout")
async def logout_action(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    network_state = NETWORK_RUNTIME.state() or _network_state()
    overview = _overview_status_payload(network_state)
    ctx = _template_context("Overview", "Control Plane")
    ctx.update({
        "status_chips": overview["status_chips"],
        "connectivity_items": overview["connectivity_items"],
        "overview_visual": overview["visual"],
        "system_metrics": _system_metrics(getattr(request.app.state, "core_ipc", None)),
        "system_uptime": _system_uptime(),
        "disk": _disk_usage(),
        "gateway_id": GATEWAY_ID,
        "domain_cards": [],
    })
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.get("/monitor", response_class=HTMLResponse)
async def monitor_page(request: Request) -> HTMLResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "monitor.html", _template_context("Monitor", "Monitor"))


@router.get("/connectivity", response_class=HTMLResponse)
async def connectivity_page(request: Request) -> HTMLResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    ctx = _template_context("Connectivity", "Connectivity")
    ctx.update({
        "connectivity_tabs": [
            {"id": "status", "label": "Status", "active": True, "disabled": False},
            {"id": "ethernet", "label": "Ethernet", "active": False, "disabled": False},
            {"id": "wifi", "label": "Wi-Fi", "active": False, "disabled": False},
            {"id": "cellular", "label": "Cellular", "active": False, "disabled": False},
            {"id": "policy", "label": "Uplink Policy", "active": False, "disabled": False},
        ],
        "network_settings": CONFIGS["network"],
        "network_state": NETWORK_RUNTIME.state() or _network_state(),
        "apply_result": _apply_result(),
    })
    return templates.TemplateResponse(request, "connectivity.html", ctx)


@router.get("/system", response_class=HTMLResponse)
async def system_page(request: Request) -> HTMLResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    ctx = _template_context("System", "System")
    ctx.update({
        "system_tabs": [
            {"id": "access", "label": "Access", "active": True, "disabled": False},
        ],
        "current_username": request.session.get("username", DEFAULT_USERNAME),
    })
    return templates.TemplateResponse(request, "system.html", ctx)


@router.get("/interfaces", response_class=HTMLResponse)
async def interfaces_page(request: Request) -> HTMLResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    ctx = _template_context("Interfaces", "Interfaces")
    ctx.update({
        "rs232_config": CONFIGS["rs232"],
        "rs485_config": CONFIGS["rs485"],
        "modbus_tcp_config": CONFIGS["modbus_tcp"],
    })
    return templates.TemplateResponse(request, "interfaces.html", ctx)


@router.get("/forwarding", response_class=HTMLResponse)
async def forwarding_page(request: Request) -> HTMLResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "forwarding.html", _template_context("Data Forwarding", "Data Forwarding"))


@router.get("/edge-server", response_class=HTMLResponse)
async def edge_server_page(request: Request) -> HTMLResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "edge_server.html", _template_context("Edge Server", "Edge Server"))


@router.get("/insights", response_class=HTMLResponse)
async def insights_page(request: Request) -> HTMLResponse:
    if not _is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "insights.html", _template_context("Insights", "Insights"))


@router.post("/api/system/access")
async def update_access(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "message": "Access settings accepted by v2 shell."})


@router.get("/api/network/settings")
async def get_network_settings(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    settings = NETWORK_RUNTIME.load_settings()
    if settings is not None:
        CONFIGS["network"] = settings
    payload = dict(CONFIGS["network"])
    payload["ok"] = True
    return JSONResponse(payload)


@router.post("/api/network/settings")
async def save_network_settings(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    payload = await request.json()
    try:
        NETWORK_RUNTIME.save_settings(payload)
    except (ValueError, OSError) as exc:
        return JSONResponse({"ok": False, "message": f"Save failed: {exc}"}, status_code=status.HTTP_400_BAD_REQUEST)
    CONFIGS["network"] = {k: v for k, v in payload.items() if k != "ok"}
    return JSONResponse({"ok": True, "message": "Network settings saved."})


@router.post("/api/network/apply")
async def apply_network_settings(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    if not NETWORK_RUNTIME.available:
        return JSONResponse({"ok": True, "apply_requested": True, "apply_result": _apply_result()})
    return JSONResponse(await asyncio.to_thread(NETWORK_RUNTIME.apply))


@router.post("/api/network/save-and-apply")
async def save_and_apply_network_settings(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    payload = await request.json()
    try:
        NETWORK_RUNTIME.save_settings(payload)
    except (ValueError, OSError) as exc:
        return JSONResponse({"ok": False, "message": f"Save failed: {exc}"}, status_code=status.HTTP_400_BAD_REQUEST)
    CONFIGS["network"] = {k: v for k, v in payload.items() if k != "ok"}
    if not NETWORK_RUNTIME.available:
        return JSONResponse({"ok": True, "apply_requested": True, "apply_result": _apply_result()})
    return JSONResponse(await asyncio.to_thread(NETWORK_RUNTIME.apply))


@router.get("/api/network/state")
async def get_network_state(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(NETWORK_RUNTIME.state() or _network_state())


@router.get("/api/network/apply-result")
async def get_network_apply_result(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(NETWORK_RUNTIME.apply_result() or _apply_result())


@router.get("/api/network/events")
async def get_network_events(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    window = request.query_params.get("window", "7d")
    limit = int(_number(request.query_params.get("limit"), 100))
    return JSONResponse(NETWORK_RUNTIME.events(window, limit))


@router.get("/api/network/events/export/csv")
async def export_network_events_csv(request: Request) -> PlainTextResponse:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    window = request.query_params.get("window", "30d")
    lines = ["timestamp,event_type,severity,iface,previous_uplink,active_uplink,duration_ms,message"]
    for event in NETWORK_RUNTIME.events(window, limit=2000).get("events", []):
        message = str(event.get("message") or event.get("reason") or "").replace('"', "'")
        lines.append(
            f'{event.get("timestamp_utc", "")},{event.get("event_type", "")},{event.get("severity", "")},'
            f'{event.get("iface", "")},{event.get("previous_uplink", "")},{event.get("active_uplink", "")},'
            f'{event.get("duration_ms", "")},"{message}"'
        )
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/csv")


@router.get("/api/network/iface-details")
async def get_iface_details(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(await asyncio.to_thread(NETWORK_RUNTIME.iface_details))


@router.post("/api/network/wifi/scan")
async def scan_wifi_networks(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    if not NETWORK_RUNTIME.available:
        return JSONResponse({"ok": True, "networks": []})
    return JSONResponse(await asyncio.to_thread(NETWORK_RUNTIME.scan_wifi, "wlan0"))


@router.post("/api/cellular/refresh-state")
async def cellular_refresh_state(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    if not NETWORK_RUNTIME.available:
        return JSONResponse({"ok": True, "cellular": _network_state()["cellular"]})
    return JSONResponse(await asyncio.to_thread(NETWORK_RUNTIME.cellular_refresh))


@router.get("/api/system/metrics")
async def get_system_metrics(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(_system_metrics(getattr(request.app.state, "core_ipc", None)))


@router.get("/api/system/metrics/history")
async def get_system_metrics_history(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(_system_metric_history(getattr(request.app.state, "core_ipc", None)))


@router.get("/api/monitor/anomaly-config")
async def get_monitor_anomaly_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    core_ipc = getattr(request.app.state, "core_ipc", None)
    window_ms = 24 * 3600 * 1000
    counts = {"Info": 0, "Warning": 0, "Critical": 0, "total": 0}
    if core_ipc is not None:
        try:
            counts = core_ipc.storage.anomaly_counts(_now_ms() - window_ms)
        except Exception as exc:  # storage optional; never fail the page
            LOGGER.warning("anomaly_counts_failed error=%s", exc)
    return JSONResponse({
        "ok": True,
        "charts": _monitor_chart_catalog(),
        "checks": ANOMALY_ENGINE_CHECKS,
        "rules": ANOMALY_RULES,
        "counts_24h": counts,
    })


@router.get("/api/monitor/timeseries")
async def get_monitor_timeseries(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    metric = request.query_params.get("metric") or ""
    valid_metrics = {chart["metric"] for chart in MONITOR_CHARTS}
    if metric not in valid_metrics:
        return JSONResponse({"ok": False, "message": "Unknown metric."}, status_code=status.HTTP_400_BAD_REQUEST)

    now = _now_ms()
    default_span = 3600 * 1000  # last hour
    from_ms = int(_number(request.query_params.get("from"), now - default_span))
    to_ms = int(_number(request.query_params.get("to"), now))
    if to_ms <= from_ms:
        from_ms, to_ms = now - default_span, now

    core_ipc = getattr(request.app.state, "core_ipc", None)
    if core_ipc is None:
        return JSONResponse({"ok": True, "metric": metric, "points": [], "anomalies": [], "tier": "fine"})
    try:
        series = core_ipc.storage.timeseries(metric, from_ms, to_ms)
        # Rebuild headlines at read time so wording stays current for old rows.
        for anomaly in series.get("anomalies", []):
            anomaly["headline"] = headline_for_stored(anomaly, metric)
    except Exception as exc:
        LOGGER.warning("timeseries_failed metric=%s error=%s", metric, exc)
        return JSONResponse({"ok": True, "metric": metric, "points": [], "anomalies": [], "tier": "fine"})
    series["ok"] = True
    series["from"] = from_ms
    series["to"] = to_ms
    return JSONResponse(series)


@router.get("/api/monitor/anomalies/recent")
async def get_monitor_recent_anomalies(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    now = _now_ms()
    since_ms = int(_number(request.query_params.get("since"), now - 24 * 3600 * 1000))
    limit = min(500, max(1, int(_number(request.query_params.get("limit"), 200))))
    core_ipc = getattr(request.app.state, "core_ipc", None)
    if core_ipc is None:
        return JSONResponse({"ok": True, "events": [], "counts": {"Info": 0, "Warning": 0, "Critical": 0, "total": 0}})
    try:
        events = core_ipc.storage.recent_anomalies(since_ms, limit)
        counts = core_ipc.storage.anomaly_counts(since_ms)
    except Exception as exc:
        LOGGER.warning("recent_anomalies_failed error=%s", exc)
        return JSONResponse({"ok": True, "events": [], "counts": {"Info": 0, "Warning": 0, "Critical": 0, "total": 0}})
    return JSONResponse({"ok": True, "events": events, "counts": counts})


@router.get("/api/monitor/anomalies/grouped")
async def get_monitor_grouped_anomalies(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    now = _now_ms()
    since_ms = int(_number(request.query_params.get("since"), now - 24 * 3600 * 1000))
    core_ipc = getattr(request.app.state, "core_ipc", None)
    if core_ipc is None:
        return JSONResponse({"ok": True, "groups": [], "counts": {"Info": 0, "Warning": 0, "Critical": 0, "total": 0}})
    try:
        groups = core_ipc.storage.grouped_anomalies(since_ms)
        counts = core_ipc.storage.anomaly_counts(since_ms)
        category_counts = core_ipc.storage.category_counts(since_ms)
    except Exception as exc:
        LOGGER.warning("grouped_anomalies_failed error=%s", exc)
        return JSONResponse({"ok": True, "groups": [], "counts": {"Info": 0, "Warning": 0, "Critical": 0, "total": 0}, "category_counts": {}})
    return JSONResponse({"ok": True, "groups": groups, "counts": counts, "category_counts": category_counts})


@router.get("/api/interfaces/rs232/config")
async def get_rs232_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    payload = dict(CONFIGS["rs232"])
    payload["ok"] = True
    return JSONResponse(payload)


@router.post("/api/interfaces/rs232/config")
async def save_rs232_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    try:
        CONFIGS["rs232"], storage = INTERFACES_SERVICE.update_section("rs232", await request.json())
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    core_ipc = await _send_config_to_core(request, "rs232", CONFIGS["rs232"])
    return JSONResponse({"ok": True, "message": "RS232 config saved.", "storage": storage, "core_ipc": core_ipc})


@router.get("/api/interfaces/rs485/config")
async def get_rs485_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    payload = dict(CONFIGS["rs485"])
    payload["ok"] = True
    return JSONResponse(payload)


@router.post("/api/interfaces/rs485/config")
async def save_rs485_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    try:
        CONFIGS["rs485"], storage = INTERFACES_SERVICE.update_section("rs485", await request.json())
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    core_ipc = await _send_config_to_core(request, "rs485", CONFIGS["rs485"])
    return JSONResponse({"ok": True, "message": "RS485 config saved.", "storage": storage, "core_ipc": core_ipc})


@router.get("/api/interfaces/modbus-tcp/config")
async def get_modbus_tcp_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    payload = dict(CONFIGS["modbus_tcp"])
    payload["ok"] = True
    return JSONResponse(payload)


@router.post("/api/interfaces/modbus-tcp/config")
async def save_modbus_tcp_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    try:
        CONFIGS["modbus_tcp"], storage = INTERFACES_SERVICE.update_section("modbus_tcp", await request.json())
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    core_ipc = await _send_config_to_core(request, "modbus_tcp", CONFIGS["modbus_tcp"])
    return JSONResponse({"ok": True, "message": "Modbus TCP config saved.", "storage": storage, "core_ipc": core_ipc})


def _interface_data_storage(request: Request) -> object | None:
    ipc = getattr(request.app.state, "core_ipc", None)
    return getattr(ipc, "interface_storage", None)


@router.get("/api/interfaces/data/sources")
async def get_interface_data_sources(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    if storage is None:
        return JSONResponse({"ok": False, "message": "Interface data storage is unavailable."}, status_code=503)
    return JSONResponse({"ok": True, "sources": storage.sources()})


@router.get("/api/interfaces/data/messages")
async def get_interface_sensor_messages(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    if storage is None:
        return JSONResponse({"ok": False, "message": "Interface data storage is unavailable."}, status_code=503)
    query = request.query_params
    rows = storage.sensor_messages(
        source_type=query.get("source_type"), source_id=query.get("source_id"),
        from_ms=int(_number(query.get("from_ms"), 0)),
        to_ms=int(_number(query.get("to_ms"), 2**63 - 1)),
        limit=int(_number(query.get("limit"), 1000)),
    )
    return JSONResponse({"ok": True, "messages": rows})


@router.get("/api/interfaces/data/readings")
async def get_interface_sensor_readings(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    if storage is None:
        return JSONResponse({"ok": False, "message": "Interface data storage is unavailable."}, status_code=503)
    query = request.query_params
    rows = storage.readings(
        source_type=query.get("source_type"), source_id=query.get("source_id"), name=query.get("name"),
        from_ms=int(_number(query.get("from_ms"), 0)),
        to_ms=int(_number(query.get("to_ms"), 2**63 - 1)),
        limit=int(_number(query.get("limit"), 5000)),
    )
    return JSONResponse({"ok": True, "readings": rows})


@router.get("/api/interfaces/data/sniffer")
async def get_interface_sniffer_frames(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    if storage is None:
        return JSONResponse({"ok": False, "message": "Interface data storage is unavailable."}, status_code=503)
    query = request.query_params
    rows = storage.sniffer_frames(
        port=query.get("port"), from_ms=int(_number(query.get("from_ms"), 0)),
        to_ms=int(_number(query.get("to_ms"), 2**63 - 1)),
        limit=int(_number(query.get("limit"), 1000)),
    )
    return JSONResponse({"ok": True, "frames": rows})


@router.get("/api/forwarding/config")
async def get_forwarding_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    gid = forwarding_gateway_id()
    payload = dict(CONFIGS["forwarding"])
    payload.update({
        "ok": True,
        "gateway_id": gid,
        "topics": forwarding_topics_for(gid),
        "available_sources": _forwarding_available_sources(request),
        "metric_interval_choices": list(METRIC_INTERVAL_CHOICES),
        "default_graphql_query": DEFAULT_GRAPHQL_QUERY,
    })
    return JSONResponse(payload)


@router.post("/api/forwarding/config")
async def save_forwarding_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    config, pending_certs = normalize_forwarding_config(await request.json())
    CONFIGS["forwarding"] = config
    service = getattr(request.app.state, "forwarding", None)
    if service is not None:
        await service.apply_config(config, pending_certs)
    else:
        persist_forwarding_config(config, pending_certs)
    return JSONResponse({"ok": True, "message": "Forwarding configuration saved and applied."})


@router.get("/api/forwarding/status")
async def get_forwarding_status(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    service = getattr(request.app.state, "forwarding", None)
    if service is not None:
        return JSONResponse(service.status())
    return JSONResponse(_forwarding_status())


@router.get("/api/forwarding/buffer-stats")
async def get_forwarding_buffer_stats(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    service = getattr(request.app.state, "forwarding", None)
    if service is not None:
        return JSONResponse(service.buffer_stats())
    return JSONResponse({
        "ok": True, "total_pending": 0, "total_replayed": 0, "total_dropped": 0,
        "success_rate": 100, "profiles": [],
        "storage": {"db_size_mb": 0, "estimated_capacity_mb": 0, "max_per_profile": 0},
    })


@router.get("/api/forwarding/events")
async def get_forwarding_events(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    service = getattr(request.app.state, "forwarding", None)
    if service is not None:
        return JSONResponse(service.events())
    return JSONResponse({"ok": True, "events": [], "summary": {"outages": 0, "recovered": 0, "errors": 0}})


@router.get("/api/forwarding/events/export/csv")
async def export_forwarding_events_csv(request: Request) -> PlainTextResponse:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    lines = ["timestamp,profile,protocol,event,severity,message"]
    service = getattr(request.app.state, "forwarding", None)
    if service is not None:
        for event in service.events(limit=1000).get("events", []):
            stamp = datetime.fromtimestamp(event["timestamp"] / 1000, UTC).isoformat()
            message = str(event.get("message", "")).replace('"', "'")
            lines.append(
                f'{stamp},{event.get("profile", "")},{event.get("protocol", "")},'
                f'{event.get("event", "")},{event.get("severity", "")},"{message}"'
            )
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/csv")


@router.get("/api/edge-server/config")
async def get_edge_server_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    previous = CONFIGS["edge_server"]
    loaded = load_saved_edge_server_config()
    if loaded is not previous:
        edge_server = getattr(request.app.state, "edge_server", None)
        if edge_server is not None:
            await edge_server.apply_config(CONFIGS["edge_server"])
            LOGGER.info("api_config_load applied_saved_config=true")
    payload = _edge_server_public_config(CONFIGS["edge_server"])
    payload["ok"] = True
    payload["forwarding_profiles"] = [
        {"id": profile.get("id"), "name": profile.get("name"), "protocol": profile.get("protocol")}
        for profile in CONFIGS["forwarding"].get("profiles", [])
    ]
    return JSONResponse(payload)


@router.post("/api/edge-server/config")
async def save_edge_server_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    try:
        CONFIGS["edge_server"] = _normalise_edge_server_config(await request.json())
        _save_edge_server_config(CONFIGS["edge_server"])
    except Exception as exc:
        LOGGER.exception("api_config_save failed error=%s", exc)
        return JSONResponse({"ok": False, "message": "Save failed."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is not None:
        await edge_server.apply_config(CONFIGS["edge_server"])
    else:
        LOGGER.error("api_config_save edge_server_task_missing")
    if (CONFIGS["edge_server"].get("funnel") or {}).get("enabled"):
        try:
            _apply_edge_server_funnel(CONFIGS["edge_server"])
        except Exception as exc:
            LOGGER.error("api_config_save funnel_reapply_failed error=%s", exc)
    listeners = CONFIGS["edge_server"].get("listeners") or {}
    enabled = [name for name in ("http", "https", "mqtt", "mqtts") if (listeners.get(name) or {}).get("enabled")]
    LOGGER.info(
        "api_config_save ok enabled=%s http_endpoints=%d mqtt_topics=%d",
        ",".join(enabled) if enabled else "none",
        len(CONFIGS["edge_server"].get("http_endpoints") or []),
        len(CONFIGS["edge_server"].get("mqtt_topics") or []),
    )
    return JSONResponse({"ok": True, "message": "Edge Server config saved."})


@router.get("/api/edge-server/funnel")
async def get_edge_server_funnel(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(_edge_server_funnel_status(CONFIGS["edge_server"]))


@router.post("/api/edge-server/funnel")
async def save_edge_server_funnel(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    try:
        payload = await request.json()
        current = _normalise_edge_server_config(CONFIGS["edge_server"])
        current["funnel"] = {
            **dict(current.get("funnel") or {}),
            "enabled": _bool_config(payload.get("enabled"), False),
            "http": _bool_config(payload.get("http"), True),
            "https": _bool_config(payload.get("https"), False),
            "mqtt": _bool_config(payload.get("mqtt"), False),
            "mqtts": _bool_config(payload.get("mqtts"), False),
        }
        CONFIGS["edge_server"] = _normalise_edge_server_config(current)
        _save_edge_server_config(CONFIGS["edge_server"])
        _apply_edge_server_funnel(CONFIGS["edge_server"])
    except Exception as exc:
        LOGGER.exception("api_funnel_save failed error=%s", exc)
        return JSONResponse({"ok": False, "message": "Public tunnel update failed."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return JSONResponse({**_edge_server_funnel_status(CONFIGS["edge_server"]), "message": "Public tunnel updated."})


@router.post("/api/edge-server/tls")
async def save_edge_server_tls(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    try:
        installed = _save_edge_server_tls(await request.json(), CONFIGS["edge_server"])
    except ValueError as exc:
        LOGGER.error("api_tls_save invalid_pem error=%s", exc)
        return JSONResponse({"ok": False, "message": "Certificate save failed."}, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        LOGGER.exception("api_tls_save failed error=%s", exc)
        return JSONResponse({"ok": False, "message": "Certificate save failed."}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is not None:
        await edge_server.reload_tls()
    else:
        LOGGER.error("api_tls_save edge_server_task_missing")
    LOGGER.info("api_tls_save ok installed=%s", installed)
    return JSONResponse({"ok": True, "message": "Certificates saved.", "installed": installed})


@router.get("/api/edge-server/status")
async def get_edge_server_status(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is not None:
        return JSONResponse(edge_server.snapshot())
    return JSONResponse(_edge_server_status())


@router.get("/api/edge-server/events")
async def get_edge_server_events(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is not None:
        return JSONResponse({"ok": True, "events": edge_server.events()})
    return JSONResponse({"ok": True, "events": []})


@router.get("/api/edge-server/http/metrics")
async def get_edge_server_http_metrics(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    minutes = _edge_server_window_minutes(request)
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is not None:
        return JSONResponse(edge_server.protocol_metrics("http", minutes=minutes))
    return JSONResponse({"ok": True, "protocol_group": "http", "total_messages": 0, "device_count": 0, "routes": [], "minute_series": [], "recent_messages": []})


@router.get("/api/edge-server/mqtt/metrics")
async def get_edge_server_mqtt_metrics(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    minutes = _edge_server_window_minutes(request)
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is not None:
        return JSONResponse(edge_server.protocol_metrics("mqtt", minutes=minutes))
    return JSONResponse({"ok": True, "protocol_group": "mqtt", "total_messages": 0, "device_count": 0, "routes": [], "minute_series": [], "recent_messages": []})


@router.get("/api/edge-server/overview/metrics")
async def get_edge_server_overview_metrics(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    minutes = _edge_server_window_minutes(request)
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is not None:
        return JSONResponse(edge_server.overview_metrics(minutes=minutes))
    return JSONResponse({
        "ok": True,
        "minutes": minutes,
        "http": {"ok": True, "protocol_group": "http", "total_messages": 0, "device_count": 0, "routes": [], "minute_series": [], "recent_messages": []},
        "mqtt": {"ok": True, "protocol_group": "mqtt", "total_messages": 0, "device_count": 0, "routes": [], "minute_series": [], "recent_messages": []},
    })


@router.get("/api/edge-server/alerts")
async def get_edge_server_alerts(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is not None:
        return JSONResponse(edge_server.alert_metrics(_edge_export_filters(request)))
    return JSONResponse({"ok": True, "summary": {"total": 0, "warning": 0, "error": 0, "critical": 0}, "events": []})


@router.get("/api/edge-server/history/devices")
async def get_edge_server_history_devices(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    edge_server = getattr(request.app.state, "edge_server", None)
    if edge_server is not None:
        return JSONResponse(edge_server.history_devices())
    return JSONResponse({"ok": True, "devices": []})


@router.get("/api/edge-server/history/device")
async def get_edge_server_device_history_query(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    device_id = request.query_params.get("device_id") or ""
    if not device_id:
        return JSONResponse({"ok": False, "message": "Device not selected."}, status_code=status.HTTP_400_BAD_REQUEST)
    edge_server = getattr(request.app.state, "edge_server", None)
    filters = {
        "protocol_group": request.query_params.get("protocol_group") or "",
        "from": request.query_params.get("from") or "",
        "to": request.query_params.get("to") or "",
    }
    if edge_server is not None:
        return JSONResponse(edge_server.device_history(device_id, filters))
    return JSONResponse({"ok": True, "device_id": device_id, "summary": {}, "message_series": [], "anomaly_series": [], "recent_events": [], "recent_messages": []})


@router.get("/api/edge-server/history/device/{device_id}")
async def get_edge_server_device_history(request: Request, device_id: str) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    edge_server = getattr(request.app.state, "edge_server", None)
    filters = {
        "protocol_group": request.query_params.get("protocol_group") or "",
        "from": request.query_params.get("from") or "",
        "to": request.query_params.get("to") or "",
    }
    if edge_server is not None:
        return JSONResponse(edge_server.device_history(device_id, filters))
    return JSONResponse({"ok": True, "device_id": device_id, "summary": {}, "message_series": [], "anomaly_series": [], "recent_events": [], "recent_messages": []})


@router.get("/api/edge-server/events.csv")
async def export_edge_server_events_csv(request: Request) -> Response:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    rows = _edge_export_rows(request, "events")
    fields = ["created_at", "severity", "event_type", "protocol", "device_id", "route", "source", "message", "details_json"]
    return _csv_download("edge-server-events.csv", rows, fields)


@router.get("/api/edge-server/events.jsonl")
async def export_edge_server_events_jsonl(request: Request) -> Response:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    rows = _edge_export_rows(request, "events")
    return _jsonl_download("edge-server-events.jsonl", rows)


@router.get("/api/edge-server/messages.csv")
async def export_edge_server_messages_csv(request: Request) -> Response:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    filters = _edge_export_filters(request)
    rows = _edge_export_rows(request, "messages", filters)
    fields = [
        "id", "received_at", "protocol", "device_id", "identity_source", "source_ip", "route",
        "endpoint_name", "payload_type", "payload_size", "payload_hash", "device_timestamp",
        "sequence", "accepted", "reject_reason", "details_json",
    ]
    if _truthy(filters.get("include_payload")):
        fields.extend(["payload_json", "payload_raw_hex"])
    return _csv_download("edge-server-messages.csv", rows, fields)


@router.get("/api/edge-server/messages.jsonl")
async def export_edge_server_messages_jsonl(request: Request) -> Response:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    rows = _edge_export_rows(request, "messages")
    return _jsonl_download("edge-server-messages.jsonl", rows)


def _insights_configured(request: Request) -> list[dict[str, Any]]:
    storage = _interface_data_storage(request)
    if storage is None:
        return []
    return insights_data.configured_devices(INTERFACES_SERVICE.snapshot(), storage)


def _insights_device(configured: list[dict[str, Any]], source: str, device_id: str) -> dict[str, Any] | None:
    for device in configured:
        if device["source"] == source and device["device_id"] == device_id:
            return device
    return None


@router.get("/api/insights/configured")
async def insights_configured(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "devices": _insights_configured(request)})


@router.get("/api/insights/live")
async def insights_live(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    if storage is None:
        return JSONResponse({"ok": True, "devices": []})
    configured = _insights_configured(request)
    live = insights_data.build_live_devices(configured, storage)
    return JSONResponse({"ok": True, "devices": live})


@router.get("/api/insights/history")
async def insights_history(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    if storage is None:
        return JSONResponse({"ok": True, "metrics": {}})
    params = request.query_params
    metric_names = [m for m in str(params.get("metrics", "")).split(",") if m]
    series = insights_data.history_series(
        storage, params.get("source", ""), params.get("device_id", ""), metric_names, params.get("window", "1h"),
    )
    return JSONResponse({"ok": True, "metrics": series})


@router.get("/api/insights/events")
async def insights_events(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    if storage is None:
        return JSONResponse({"ok": True, "events": []})
    configured = _insights_configured(request)
    INSIGHTS_EVENTS.evaluate(ALERT_RULES, configured, storage)
    params = request.query_params
    events = INSIGHTS_EVENTS.query(
        storage,
        window_ms=insights_data.WINDOW_MS.get(params.get("window", "24h"), insights_data.WINDOW_MS["24h"]),
        severity=params.get("severity", ""),
        source=params.get("source", ""),
        device_id=params.get("device_id", ""),
        device_lookup={(d["source"], d["device_id"]): d for d in configured},
    )
    return JSONResponse({"ok": True, "events": events})


@router.get("/api/insights/alert-rules")
async def get_alert_rules(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "rules": ALERT_RULES})


@router.post("/api/insights/alert-rules")
async def create_alert_rule(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    global NEXT_RULE_ID
    payload = await request.json()
    rule = {
        "id": NEXT_RULE_ID,
        "source": payload.get("source", ""),
        "device_id": payload.get("device_id", ""),
        "metric_name": payload.get("metric_name", ""),
        "condition": payload.get("condition", "gt"),
        "threshold": payload.get("threshold", 0),
        "severity": payload.get("severity", "warning"),
        "enabled": True,
    }
    NEXT_RULE_ID += 1
    ALERT_RULES.append(rule)
    insights_data.save_alert_rules(ALERT_RULES)
    return JSONResponse({"ok": True, "rule": rule})


@router.delete("/api/insights/alert-rules/{rule_id}")
async def delete_alert_rule(request: Request, rule_id: int) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    ALERT_RULES[:] = [rule for rule in ALERT_RULES if rule["id"] != rule_id]
    insights_data.save_alert_rules(ALERT_RULES)
    return JSONResponse({"ok": True})


@router.put("/api/insights/alert-rules/{rule_id}")
async def toggle_alert_rule(request: Request, rule_id: int) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    payload = await request.json()
    for rule in ALERT_RULES:
        if rule["id"] == rule_id:
            rule["enabled"] = bool(payload["enabled"]) if "enabled" in payload else not bool(rule.get("enabled"))
            insights_data.save_alert_rules(ALERT_RULES)
            return JSONResponse({"ok": True, "rule": rule})
    return JSONResponse({"ok": False, "message": "Rule not found."}, status_code=status.HTTP_404_NOT_FOUND)


@router.get("/api/insights/summary")
async def insights_summary(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    configured = _insights_configured(request)
    live = insights_data.build_live_devices(configured, storage) if storage else []
    return JSONResponse(insights_data.summary(configured, live))


@router.get("/api/insights/stats")
async def insights_stats(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    if storage is None:
        return JSONResponse({"ok": True, "stats": {}})
    params = request.query_params
    source, device_id = params.get("source", ""), params.get("device_id", "")
    device = _insights_device(_insights_configured(request), source, device_id)
    if device is None:
        return JSONResponse({"ok": True, "stats": {}})
    metric_names = [m["name"] for m in device["expected_metrics"]]
    stats = insights_data.rolling_stats(storage, source, device_id, metric_names, device.get("poll_interval_ms", 1000))
    return JSONResponse({"ok": True, "stats": stats})


@router.get("/api/insights/trends")
async def insights_trends(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    storage = _interface_data_storage(request)
    if storage is None:
        return JSONResponse({"ok": True, "trends": []})
    params = request.query_params
    source, device_id = params.get("source", ""), params.get("device_id", "")
    device = _insights_device(_insights_configured(request), source, device_id)
    if device is None:
        return JSONResponse({"ok": True, "trends": []})
    metric_names = [m["name"] for m in device["expected_metrics"]]
    trends = insights_data.compute_trends(storage, source, device_id, metric_names, ALERT_RULES)
    return JSONResponse({"ok": True, "trends": trends})


@router.get("/api/insights/export/csv")
async def export_insights_csv(request: Request) -> Response:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    storage = _interface_data_storage(request)
    params = request.query_params
    source, device_id = params.get("source", ""), params.get("device_id", "")
    requested = [m for m in str(params.get("metrics", "")).split(",") if m]
    if storage is None:
        rows: list[dict[str, Any]] = []
    else:
        if requested == ["all"]:
            requested = [m["name"] for m in storage.distinct_reading_names(source, device_id)]
        rows = insights_data.export_csv_rows(storage, source, device_id, requested, params.get("window", "1h"))
    filename = f"{params.get('name') or device_id or 'sensor'}-readings.csv".replace(" ", "_")
    return _csv_download(filename, rows, ["timestamp", "source", "device_id", "metric", "value", "unit", "quality"])


@router.get("/api/engine/health")
async def engine_health(request: Request) -> JSONResponse:
    client = request.app.state.engine_client
    return JSONResponse(await client.health())


@router.get("/api/core-ipc/status")
async def core_ipc_status(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    ipc = getattr(request.app.state, "core_ipc", None)
    if ipc is None:
        return JSONResponse({"enabled": False, "connected": False, "state": "not_started"})
    return JSONResponse(ipc.snapshot())


@router.post("/api/core-ipc/send")
async def core_ipc_send(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    ipc = getattr(request.app.state, "core_ipc", None)
    if ipc is None:
        return JSONResponse({"ok": False, "message": "IPC task is not started."}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    payload = await request.json()
    message = str(payload.get("message", ""))
    if not message:
        return JSONResponse({"ok": False, "message": "message is required."}, status_code=status.HTTP_400_BAD_REQUEST)

    try:
        await ipc.send_text(message)
    except Exception as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return JSONResponse({"ok": True, "status": ipc.snapshot()})
