"""Forwarding configuration: schema, disk persistence, certificates, identity.

Profiles describe upstream destinations (MQTT broker or HTTPS endpoint) plus
which gateway data each one carries. Config lives at
/opt/metacrust/config/forwarding/config.json (env override, home fallback for
dev machines); uploaded PEMs are stored under a sibling certs/{profile_id}/
directory and only *_loaded flags travel back to the browser.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("/opt/metacrust/config/forwarding/config.json")
FALLBACK_CONFIG_PATH = Path.home() / ".metacrust" / "config" / "forwarding" / "config.json"

DEFAULT_GRAPHQL_QUERY = (
    "mutation Ingest($events: [JSON!]!) { ingestGatewayData(events: $events) }"
)

METRIC_INTERVAL_CHOICES = (1, 5, 10, 30, 60, 300)

# PEM slots per protocol block: config key -> stored file name
_CERT_SLOTS = {"tls_ca": "ca.pem", "tls_cert": "cert.pem", "tls_key": "key.pem"}


def config_path() -> Path:
    override = os.environ.get("METACRUST_FORWARDING_CONFIG_PATH")
    if override:
        return Path(override)
    if _writable_parent(DEFAULT_CONFIG_PATH):
        return DEFAULT_CONFIG_PATH
    return FALLBACK_CONFIG_PATH


def certs_dir() -> Path:
    override = os.environ.get("METACRUST_FORWARDING_CERTS_DIR")
    if override:
        return Path(override)
    return config_path().parent / "certs"


def _writable_parent(path: Path) -> bool:
    for candidate in (path.parent, *path.parent.parents):
        if candidate.exists():
            return os.access(candidate, os.W_OK)
    return False


def gateway_id() -> str:
    """Stable unit identity derived from the primary NIC MAC address."""
    override = os.environ.get("METACRUST_GATEWAY_ID")
    if override:
        return override
    candidates = ["eth0", "eth1", "wlan0"]
    net = Path("/sys/class/net")
    if net.is_dir():
        for name in sorted(p.name for p in net.iterdir()):
            if name not in candidates and name != "lo":
                candidates.append(name)
        for name in candidates:
            mac_path = net / name / "address"
            try:
                mac = mac_path.read_text().strip().lower().replace(":", "")
            except OSError:
                continue
            if re.fullmatch(r"[0-9a-f]{12}", mac) and mac != "000000000000":
                return f"mcx-{mac}"
    try:
        machine = Path("/etc/machine-id").read_text().strip()[:12]
        if machine:
            return f"mcx-{machine}"
    except OSError:
        pass
    return "mcx-unknown"


def default_config() -> dict[str, Any]:
    return {"version": 3, "profiles": []}


def _default_sources() -> dict[str, Any]:
    return {
        "device_metrics": False,
        "metrics_interval_s": 5,
        "device_anomalies": False,
        "sensors": [],
    }


def _normalize_sources(raw: Any) -> dict[str, Any]:
    sources = _default_sources()
    if not isinstance(raw, dict):
        return sources
    sources["device_metrics"] = bool(raw.get("device_metrics", False))
    sources["device_anomalies"] = bool(raw.get("device_anomalies", False))
    try:
        interval = int(raw.get("metrics_interval_s") or 5)
    except (TypeError, ValueError):
        interval = 5
    sources["metrics_interval_s"] = min(3600, max(1, interval))
    sensors = raw.get("sensors")
    if sensors == "all":
        sources["sensors"] = "all"
    elif isinstance(sensors, list):
        sources["sensors"] = [str(item)[:120] for item in sensors][:64]
    return sources


def https_url(block: dict[str, Any]) -> str:
    """Compose the endpoint URL from the form's host/port/path fields."""
    host = str(block.get("host") or "").strip()
    if not host:
        return ""
    scheme = "https" if block.get("tls", True) else "http"
    port = int(block.get("port") or (443 if scheme == "https" else 80))
    default_port = 443 if scheme == "https" else 80
    path = str(block.get("path") or "/ingest")
    if not path.startswith("/"):
        path = "/" + path
    port_part = "" if port == default_port else f":{port}"
    return f"{scheme}://{host}{port_part}{path}"


def auth_headers_spec(block: dict[str, Any]) -> dict[str, Any]:
    """Translate the form's auth_type/auth_value pair into a publisher auth spec."""
    kind = str(block.get("auth_type") or "none").lower()
    value = str(block.get("auth_value") or "")
    if kind == "bearer" and value:
        return {"type": "bearer", "token": value}
    if kind == "api_key" and value:
        return {"type": "header", "header_name": "X-API-Key", "header_value": value}
    if kind == "basic" and value:
        username, _, password = value.partition(":")
        return {"type": "basic", "username": username, "password": password}
    return {"type": "none"}


def normalize_config(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """Normalize a raw config payload.

    Returns (config, pending_certs) where pending_certs maps
    profile_id -> {file_name: pem_content} for PEMs uploaded in this request;
    save_config() writes them to disk. PEM contents never stay in the config.
    """
    profiles: list[dict[str, Any]] = []
    pending_certs: dict[str, dict[str, str]] = {}

    for raw in (payload.get("profiles") or [])[:6]:
        if not isinstance(raw, dict):
            continue
        profile: dict[str, Any] = {}
        profile["id"] = re.sub(r"[^A-Za-z0-9_-]", "", str(raw.get("id") or secrets.token_hex(8)))[:32] or secrets.token_hex(8)
        profile["name"] = str(raw.get("name") or "Unnamed Profile")[:64]
        protocol = str(raw.get("protocol") or "mqtt").lower()
        profile["protocol"] = protocol if protocol in ("mqtt", "https") else "mqtt"
        profile["enabled"] = bool(raw.get("enabled", False))
        profile["sources"] = _normalize_sources(raw.get("sources"))

        certs: dict[str, str] = {}
        if profile["protocol"] == "mqtt":
            m = dict(raw.get("mqtt") or {})
            block = {
                "host": str(m.get("host") or "")[:253],
                "port": _port(m.get("port"), 1883),
                "client_id": str(m.get("client_id") or "")[:128],
                "username": str(m.get("username") or "")[:128],
                "password": str(m.get("password") or "")[:256],
                "qos": min(2, max(0, _int(m.get("qos"), 1))),
                "tls": bool(m.get("tls")),
                "mtls": bool(m.get("mtls")),
            }
            certs = _extract_certs(m)
            for slot in _CERT_SLOTS:
                block[f"{slot}_loaded"] = bool(m.get(f"{slot}_loaded")) or slot in certs
            profile["mqtt"] = block
        else:
            h = dict(raw.get("https") or {})
            mode = str(h.get("mode") or "rest").lower()
            auth_type = str(h.get("auth_type") or "none").lower()
            path = str(h.get("path") or h.get("sensor_path") or "/ingest")[:512]
            block = {
                "host": str(h.get("host") or "")[:253],
                "port": _port(h.get("port"), 443),
                "path": path,
                "tls": bool(h.get("tls", True)),
                "mode": mode if mode in ("rest", "graphql") else "rest",
                "graphql_query": str(h.get("graphql_query") or DEFAULT_GRAPHQL_QUERY)[:4000],
                "auth_type": auth_type if auth_type in ("none", "bearer", "api_key", "basic") else "none",
                "auth_value": str(h.get("auth_value") or "")[:512],
                "mtls": bool(h.get("mtls")),
                "verify_tls": bool(h.get("verify_tls", True)),
            }
            certs = _extract_certs(h)
            for slot in _CERT_SLOTS:
                block[f"{slot}_loaded"] = bool(h.get(f"{slot}_loaded")) or slot in certs
            profile["https"] = block

        if certs:
            pending_certs[profile["id"]] = certs
        profiles.append(profile)

    return {"version": 3, "profiles": profiles}, pending_certs


def _extract_certs(block: dict[str, Any]) -> dict[str, str]:
    """Pull inline PEM contents out of a protocol block (they never persist in JSON)."""
    found: dict[str, str] = {}
    for slot, file_name in _CERT_SLOTS.items():
        content = block.pop(slot, None)
        if isinstance(content, str) and "-----BEGIN" in content and len(content) < 65536:
            found[slot] = content
    return found


def save_config(config: dict[str, Any], pending_certs: dict[str, dict[str, str]] | None = None) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if pending_certs:
        base = certs_dir()
        for profile_id, slots in pending_certs.items():
            profile_dir = base / profile_id
            profile_dir.mkdir(parents=True, exist_ok=True)
            for slot, content in slots.items():
                target = profile_dir / _CERT_SLOTS[slot]
                target.write_text(content)
                target.chmod(0o600)

    # keep certs for profiles that no longer exist out of the way (harmless);
    # write config atomically so a power cut can't half-write it
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".fwd-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(config, handle, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def load_config() -> dict[str, Any]:
    path = config_path()
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return default_config()
    if not isinstance(raw, dict):
        return default_config()
    config, _ = normalize_config(raw)
    return config


def cert_paths(profile_id: str) -> dict[str, Path]:
    """Existing PEM files for a profile: {'tls_ca': Path, ...} (only present files)."""
    base = certs_dir() / re.sub(r"[^A-Za-z0-9_-]", "", profile_id)
    found: dict[str, Path] = {}
    for slot, file_name in _CERT_SLOTS.items():
        candidate = base / file_name
        if candidate.is_file():
            found[slot] = candidate
    return found


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _port(value: Any, default: int) -> int:
    return min(65535, max(1, _int(value, default)))
