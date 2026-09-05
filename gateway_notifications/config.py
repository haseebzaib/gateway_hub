"""Notification channels and the rules that select what each one receives.

Operators should not have to watch the dashboard to learn that data stopped
flowing. A channel is somewhere to send to — a webhook or an email — plus a
filter saying which events it wants, so one gateway can page on-call for
outages while sending everything to an ops chat room.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(
    os.environ.get("METACRUST_NOTIFICATIONS_CONFIG_PATH", "/opt/metacrust/config/notifications/config.json")
)

# Webhook flavours. Each is a real service's expected body shape, so an operator
# pastes the URL their provider gave them and it works without a transform step.
CHANNEL_TYPES = ("generic", "slack", "teams", "discord", "pagerduty", "email")

# What can be notified about. These map onto incident transitions wherever
# possible, because incidents are already one-per-problem and already know when
# they recovered — which is what keeps a single fault from paging repeatedly.
EVENT_TYPES = {
    "source_offline": "Device or source offline / stopped reporting",
    "destination_unavailable": "Forwarding destination unavailable",
    "gateway_outage": "Gateway or internet outage",
    "uplink_failover": "Failover to a backup uplink",
    "sensor_anomaly_critical": "Critical sensor or process anomaly",
    "buffer_threshold": "Buffer approaching its configured capacity",
    "recovery": "Recovery / restoration",
}

DEFAULT_EVENTS = list(EVENT_TYPES)
SEVERITIES = ("info", "warning", "critical")


def default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "channels": [],
        "rules": {
            # Warn while there is still room to act, rather than at the point
            # data is already being dropped.
            "buffer_warn_percent": 80,
            # A channel that keeps failing is retried this many times, with
            # exponential backoff, before the notification is abandoned.
            "max_retries": 4,
            # Never send more than this many notifications per hour, whatever
            # the gateway is doing. A storm must not become an email flood.
            "max_per_hour": 30,
        },
    }


def load_config() -> dict[str, Any]:
    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return default_config()
    return normalize_config(raw if isinstance(raw, dict) else {})


def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    config = normalize_config(payload)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    return config


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    base = default_config()
    rules = raw.get("rules") if isinstance(raw.get("rules"), dict) else {}
    base["rules"] = {
        "buffer_warn_percent": _clamp(rules.get("buffer_warn_percent"), 80, 1, 100),
        "max_retries": _clamp(rules.get("max_retries"), 4, 0, 10),
        "max_per_hour": _clamp(rules.get("max_per_hour"), 30, 1, 500),
    }
    channels = raw.get("channels") if isinstance(raw.get("channels"), list) else []
    base["channels"] = [normalize_channel(item) for item in channels if isinstance(item, dict)]
    return base


def normalize_channel(raw: dict[str, Any]) -> dict[str, Any]:
    kind = str(raw.get("type") or "generic")
    if kind not in CHANNEL_TYPES:
        kind = "generic"
    events = [e for e in (raw.get("events") or DEFAULT_EVENTS) if e in EVENT_TYPES]
    severity = str(raw.get("min_severity") or "warning")
    channel = {
        "id": str(raw.get("id") or secrets.token_hex(8)),
        "name": str(raw.get("name") or "Notification channel")[:80],
        "type": kind,
        "enabled": bool(raw.get("enabled", True)),
        "events": events or list(DEFAULT_EVENTS),
        "min_severity": severity if severity in SEVERITIES else "warning",
    }
    if kind == "email":
        email = raw.get("email") if isinstance(raw.get("email"), dict) else {}
        channel["email"] = {
            "smtp_host": str(email.get("smtp_host") or "")[:253],
            "smtp_port": _clamp(email.get("smtp_port"), 587, 1, 65535),
            "use_tls": bool(email.get("use_tls", True)),
            "username": str(email.get("username") or "")[:128],
            # Kept as configured; the API never returns it to the browser.
            "password": str(email.get("password") or ""),
            "from_address": str(email.get("from_address") or "")[:254],
            "to_addresses": [str(a)[:254] for a in (email.get("to_addresses") or []) if str(a).strip()][:20],
        }
    else:
        channel["url"] = str(raw.get("url") or "")[:2048]
        headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
        channel["headers"] = {str(k)[:64]: str(v)[:512] for k, v in list(headers.items())[:10]}
        # Generic receivers often want to verify the sender; when set, bodies are
        # signed with HMAC-SHA256 in the X-MetaCrust-Signature header.
        channel["secret"] = str(raw.get("secret") or "")[:256]
    return channel


def redact(config: dict[str, Any]) -> dict[str, Any]:
    """Config safe to hand the browser: secrets replaced by a set/unset flag."""
    out = json.loads(json.dumps(config))
    for channel in out.get("channels") or []:
        if channel.get("type") == "email":
            email = channel.get("email") or {}
            email["password_set"] = bool(email.pop("password", ""))
        else:
            channel["secret_set"] = bool(channel.pop("secret", ""))
    return out


def merge_secrets(incoming: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """Carry stored secrets forward when the browser sends back a redacted copy.

    The UI never receives a password or signing secret, so a plain save would
    otherwise wipe them.
    """
    by_id = {c.get("id"): c for c in (existing.get("channels") or [])}
    for channel in incoming.get("channels") or []:
        previous = by_id.get(channel.get("id"))
        if not previous:
            continue
        if channel.get("type") == "email":
            email = channel.setdefault("email", {})
            if not email.get("password"):
                email["password"] = (previous.get("email") or {}).get("password", "")
        elif not channel.get("secret"):
            channel["secret"] = previous.get("secret", "")
    return incoming


def _clamp(value: Any, fallback: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return fallback
