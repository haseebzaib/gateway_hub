from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


router = APIRouter()
PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))

GATEWAY_ID = "metacrust_v2_dev"
DEFAULT_USERNAME = "gateway"
DEFAULT_PASSWORD = "gateway"


def _file_hash(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()[:10]
    except Exception:
        return "dev"


templates.env.globals["js_hash"] = _file_hash(PACKAGE_DIR / "static" / "js" / "app.js")
templates.env.globals["css_hash"] = _file_hash(PACKAGE_DIR / "static" / "css" / "app.css")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def _json_auth_required(request: Request) -> JSONResponse | None:
    if _is_authenticated(request):
        return None
    return JSONResponse({"ok": False, "message": "Authentication required."}, status_code=status.HTTP_401_UNAUTHORIZED)


def _primary_sections(active_label: str) -> list[dict[str, object]]:
    items = [
        ("Overview", "Over", "/dashboard"),
        ("Monitor", "Mon", "/monitor"),
        ("Insights", "Info", "/insights"),
        ("Interfaces", "I/O", "/interfaces"),
        ("Data Forwarding", "Fwd", "/forwarding"),
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
    return "v2 shell"


def _disk_usage() -> dict[str, object]:
    return {"pct": 0, "used_gb": 0, "total_gb": 0}


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
                "country_code": "PK",
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
                "country_code": "PK",
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


def _system_metrics() -> dict[str, Any]:
    now = _now_ms()
    return {
        "ok": True,
        "timestamp_ms": now,
        "cpu": {
            "total_percent": 0,
            "per_core": [{"core": i, "usage_percent": 0} for i in range(4)],
            "load_average": {"1m": 0, "5m": 0, "15m": 0},
        },
        "memory": {"memory_bytes": {"used_percent": 0, "used": 0, "total": 0}},
        "temperature_c": None,
        "filesystem": {"used_percent": 0, "used_bytes": 0, "total_bytes": 0},
        "network": {
            "eth0": {"rates": {"rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0}, "totals": {"rx_bytes": 0, "tx_bytes": 0}},
            "eth1": {"rates": {"rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0}, "totals": {"rx_bytes": 0, "tx_bytes": 0}},
            "wlan0": {"rates": {"rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0}, "totals": {"rx_bytes": 0, "tx_bytes": 0}},
        },
    }


def _system_metric_history() -> dict[str, Any]:
    samples = []
    now = _now_ms()
    for i in range(30, 0, -1):
        samples.append({
            "timestamp_ms": now - i * 10_000,
            "cpu_total_percent": 0,
            "memory_used_percent": 0,
            "temperature_c": 0,
            "network": {
                "eth0": {"rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0},
                "eth1": {"rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0},
                "wlan0": {"rx_bytes_per_sec": 0, "tx_bytes_per_sec": 0},
            },
        })
    return {"ok": True, "samples": samples}


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


CONFIGS: dict[str, dict[str, Any]] = {
    "network": _network_settings(),
    "rs232": _default_rs232_config(),
    "rs485": _default_rs485_config(),
    "modbus_tcp": _default_modbus_tcp_config(),
    "forwarding": {"version": 2, "profiles": []},
}

ALERT_RULES: list[dict[str, Any]] = []
NEXT_RULE_ID = 1


def _normalise_forwarding_config(payload: dict[str, Any]) -> dict[str, Any]:
    profiles = []
    for raw in payload.get("profiles") or []:
        if not isinstance(raw, dict):
            continue
        profile = dict(raw)
        profile["id"] = str(profile.get("id") or secrets.token_hex(8))[:32]
        profile["name"] = str(profile.get("name") or "Unnamed Profile")[:64]
        profile["protocol"] = str(profile.get("protocol") or "mqtt").lower()
        if profile["protocol"] not in ("mqtt", "https"):
            profile["protocol"] = "mqtt"
        profile["enabled"] = bool(profile.get("enabled", False))
        profile["scope"] = str(profile.get("scope") or "all")
        if profile["protocol"] == "mqtt":
            mqtt = dict(profile.get("mqtt") or {})
            mqtt["tls_ca_loaded"] = bool(mqtt.pop("tls_ca", None)) or bool(mqtt.get("tls_ca_loaded"))
            mqtt["tls_cert_loaded"] = bool(mqtt.pop("tls_cert", None)) or bool(mqtt.get("tls_cert_loaded"))
            mqtt["tls_key_loaded"] = bool(mqtt.pop("tls_key", None)) or bool(mqtt.get("tls_key_loaded"))
            profile["mqtt"] = mqtt
            profile.pop("https", None)
        else:
            https = dict(profile.get("https") or {})
            https["tls_ca_loaded"] = bool(https.pop("tls_ca", None)) or bool(https.get("tls_ca_loaded"))
            https["tls_cert_loaded"] = bool(https.pop("tls_cert", None)) or bool(https.get("tls_cert_loaded"))
            https["tls_key_loaded"] = bool(https.pop("tls_key", None)) or bool(https.get("tls_key_loaded"))
            profile["https"] = https
            profile.pop("mqtt", None)
        profiles.append(profile)
    return {"version": 2, "profiles": profiles[:6]}


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
    network_state = _network_state()
    overview = _overview_status_payload(network_state)
    ctx = _template_context("Overview", "Control Plane")
    ctx.update({
        "status_chips": overview["status_chips"],
        "connectivity_items": overview["connectivity_items"],
        "overview_visual": overview["visual"],
        "system_metrics": _system_metrics(),
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
        "network_state": _network_state(),
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
            {"id": "identity", "label": "Identity", "active": False, "disabled": True},
            {"id": "services", "label": "Services", "active": False, "disabled": True},
            {"id": "updates", "label": "Updates", "active": False, "disabled": True},
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
    payload = dict(CONFIGS["network"])
    payload["ok"] = True
    return JSONResponse(payload)


@router.post("/api/network/settings")
async def save_network_settings(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    CONFIGS["network"] = await request.json()
    return JSONResponse({"ok": True, "message": "Network settings saved in hub mock state."})


@router.post("/api/network/apply")
async def apply_network_settings(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "apply_requested": True, "apply_result": _apply_result()})


@router.post("/api/network/save-and-apply")
async def save_and_apply_network_settings(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    CONFIGS["network"] = await request.json()
    return JSONResponse({"ok": True, "apply_requested": True, "apply_result": _apply_result()})


@router.get("/api/network/state")
async def get_network_state(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(_network_state())


@router.get("/api/network/apply-result")
async def get_network_apply_result(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(_apply_result())


@router.get("/api/network/events")
async def get_network_events(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "events": [], "open_outage": None, "summary": {}})


@router.get("/api/network/events/export/csv")
async def export_network_events_csv(request: Request) -> PlainTextResponse:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    return PlainTextResponse("timestamp,event_type,severity,message\n", media_type="text/csv")


@router.get("/api/network/iface-details")
async def get_iface_details(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    iface = request.query_params.get("iface", "eth0")
    return JSONResponse({"ok": True, "iface": iface, "mac": "—", "operstate": "down", "mtu": "—", "speed": "—", "ipv4": "—", "ipv6": [], "gateway": "—", "dns": []})


@router.post("/api/network/wifi/scan")
async def scan_wifi_networks(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "networks": []})


@router.post("/api/cellular/refresh-state")
async def cellular_refresh_state(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "cellular": _network_state()["cellular"]})


@router.get("/api/system/metrics")
async def get_system_metrics(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(_system_metrics())


@router.get("/api/system/metrics/history")
async def get_system_metrics_history(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(_system_metric_history())


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
    CONFIGS["rs232"] = await request.json()
    return JSONResponse({"ok": True, "message": "RS232 config saved in hub mock state."})


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
    CONFIGS["rs485"] = await request.json()
    return JSONResponse({"ok": True, "message": "RS485 config saved in hub mock state."})


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
    CONFIGS["modbus_tcp"] = await request.json()
    return JSONResponse({"ok": True, "message": "Modbus TCP config saved in hub mock state."})


@router.get("/api/forwarding/config")
async def get_forwarding_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    payload = dict(CONFIGS["forwarding"])
    payload["ok"] = True
    payload["gateway_id"] = GATEWAY_ID
    return JSONResponse(payload)


@router.post("/api/forwarding/config")
async def save_forwarding_config(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    CONFIGS["forwarding"] = _normalise_forwarding_config(await request.json())
    return JSONResponse({"ok": True, "message": "Forwarding config saved in hub mock state."})


@router.get("/api/forwarding/status")
async def get_forwarding_status(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse(_forwarding_status())


@router.get("/api/forwarding/buffer-stats")
async def get_forwarding_buffer_stats(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    profiles = [
        {
            "profile_id": p.get("id"),
            "pending": 0,
            "replayed": 0,
            "dropped": 0,
            "history": [0, 0, 0, 0, 0],
        }
        for p in CONFIGS["forwarding"].get("profiles", [])
    ]
    return JSONResponse({
        "ok": True,
        "total_pending": 0,
        "total_replayed": 0,
        "total_dropped": 0,
        "success_rate": 100,
        "profiles": profiles,
        "storage": {"db_size_mb": 0, "estimated_capacity_mb": 0, "max_per_profile": 0},
    })


@router.get("/api/forwarding/events")
async def get_forwarding_events(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "events": [], "summary": {"outages": 0, "recovered": 0, "errors": 0}})


@router.get("/api/forwarding/events/export/csv")
async def export_forwarding_events_csv(request: Request) -> PlainTextResponse:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    return PlainTextResponse("timestamp,profile,protocol,event,severity,message\n", media_type="text/csv")


@router.get("/api/insights/configured")
async def insights_configured(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "configured_devices": [], "devices": [], "metrics": []})


@router.get("/api/insights/live")
async def insights_live(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "devices": [], "summary": {"active_devices": 0, "configured_devices": 0, "good_readings": 0, "total_readings": 0, "anomalies": 0}})


@router.get("/api/insights/history")
async def insights_history(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "timestamps": [], "series": {}, "avg": [], "min": [], "max": [], "count": []})


@router.get("/api/insights/events")
async def insights_events(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "events": []})


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
    return JSONResponse({"ok": True, "rule": rule})


@router.delete("/api/insights/alert-rules/{rule_id}")
async def delete_alert_rule(request: Request, rule_id: int) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    ALERT_RULES[:] = [rule for rule in ALERT_RULES if rule["id"] != rule_id]
    return JSONResponse({"ok": True})


@router.put("/api/insights/alert-rules/{rule_id}")
async def toggle_alert_rule(request: Request, rule_id: int) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    for rule in ALERT_RULES:
        if rule["id"] == rule_id:
            rule["enabled"] = not bool(rule.get("enabled"))
            return JSONResponse({"ok": True, "rule": rule})
    return JSONResponse({"ok": False, "message": "Rule not found."}, status_code=status.HTTP_404_NOT_FOUND)


@router.get("/api/insights/summary")
async def insights_summary(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({
        "ok": True,
        "total_devices": 0,
        "live_devices": 0,
        "anomaly_count": 0,
        "active_devices": 0,
        "configured_devices": 0,
        "data_quality": 0,
        "health": 0,
    })


@router.get("/api/insights/stats")
async def insights_stats(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "stats": [], "windows": {}})


@router.get("/api/insights/trends")
async def insights_trends(request: Request) -> JSONResponse:
    if auth := _json_auth_required(request):
        return auth
    return JSONResponse({"ok": True, "trends": []})


@router.get("/api/insights/export/csv")
async def export_insights_csv(request: Request) -> PlainTextResponse:
    if not _is_authenticated(request):
        return PlainTextResponse("Authentication required.", status_code=status.HTTP_401_UNAUTHORIZED)
    return PlainTextResponse("timestamp,source,device_id,metric,value,unit,quality\n", media_type="text/csv")


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
