"""Delivery to each supported destination.

Every function here is blocking and is called from a worker thread — never from
the event loop, which serves IPC, the console and forwarding.

Each webhook flavour builds the body its provider actually expects, so an
operator pastes the URL their provider gave them and it works. A generic
receiver gets the whole notification as JSON, which is what integration tools
(n8n, Zapier, Make, custom endpoints) want.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any


TIMEOUT_S = 15.0
USER_AGENT = "MetaCrust-Gateway/1.0"

_SEVERITY_COLOUR = {"critical": "#d93025", "warning": "#f0a64b", "info": "#39d0c8"}
_PAGERDUTY_SEVERITY = {"critical": "critical", "warning": "warning", "info": "info"}


def deliver(channel: dict[str, Any], note: dict[str, Any]) -> None:
    """Send one notification. Raises on failure so the caller can retry."""
    kind = channel.get("type")
    if kind == "email":
        _send_email(channel, note)
        return
    url = str(channel.get("url") or "").strip()
    if not url:
        raise ValueError("channel has no URL configured")
    body = build_body(kind, note)
    _post(url, body, channel)


def build_body(kind: str, note: dict[str, Any]) -> dict[str, Any]:
    """The provider-shaped payload for a notification."""
    if kind == "slack":
        return _slack_body(note)
    if kind == "teams":
        return _teams_body(note)
    if kind == "discord":
        return _discord_body(note)
    if kind == "pagerduty":
        return _pagerduty_body(note)
    return _generic_body(note)


# ── payload shapes ───────────────────────────────────────────────────────

def _generic_body(note: dict[str, Any]) -> dict[str, Any]:
    """Everything we know, unopinionated, for custom receivers."""
    return {
        "source": "metacrust-gateway",
        "gateway_id": note.get("gateway_id"),
        "event": note.get("event"),
        "severity": note.get("severity"),
        "incident_ref": note.get("incident_ref"),
        "title": note.get("title"),
        "message": note.get("message"),
        "failure_domain": note.get("failure_domain"),
        "started_at": note.get("started_at"),
        "resolved_at": note.get("resolved_at"),
        "buffered_records": note.get("buffered_records"),
        "affected": note.get("affected") or [],
        "dashboard_url": note.get("dashboard_url"),
        "timestamp": note.get("timestamp"),
    }


def _slack_body(note: dict[str, Any]) -> dict[str, Any]:
    ref = note.get("incident_ref") or ""
    fields = [f"*{k}*\n{v}" for k, v in _facts(note)]
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": _subject(note)[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": note.get("message") or ""}},
    ]
    if fields:
        blocks.append({"type": "section", "fields": [
            {"type": "mrkdwn", "text": f[:2000]} for f in fields[:10]
        ]})
    if note.get("dashboard_url"):
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"<{note['dashboard_url']}|Open {ref} in the gateway console>"},
        ]})
    return {"text": _subject(note), "blocks": blocks}


def _teams_body(note: dict[str, Any]) -> dict[str, Any]:
    card: dict[str, Any] = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": _subject(note),
        "themeColor": _SEVERITY_COLOUR.get(str(note.get("severity")), "#39d0c8").lstrip("#"),
        "title": _subject(note),
        "text": note.get("message") or "",
        "sections": [{"facts": [{"name": k, "value": str(v)} for k, v in _facts(note)]}],
    }
    if note.get("dashboard_url"):
        card["potentialAction"] = [{
            "@type": "OpenUri",
            "name": "Open in gateway console",
            "targets": [{"os": "default", "uri": note["dashboard_url"]}],
        }]
    return card


def _discord_body(note: dict[str, Any]) -> dict[str, Any]:
    colour = int(_SEVERITY_COLOUR.get(str(note.get("severity")), "#39d0c8").lstrip("#"), 16)
    embed: dict[str, Any] = {
        "title": _subject(note)[:256],
        "description": (note.get("message") or "")[:4000],
        "color": colour,
        "fields": [{"name": k, "value": str(v)[:1024], "inline": True} for k, v in _facts(note)][:25],
    }
    if note.get("dashboard_url"):
        embed["url"] = note["dashboard_url"]
    return {"embeds": [embed]}


def _pagerduty_body(note: dict[str, Any]) -> dict[str, Any]:
    """Events API v2. The incident reference is the dedup key, so PagerDuty
    groups our alerts exactly as the gateway groups them, and a recovery
    notification resolves the alert it opened rather than raising a new one."""
    resolved = note.get("event") == "recovery"
    return {
        "routing_key": note.get("routing_key") or "",
        "event_action": "resolve" if resolved else "trigger",
        "dedup_key": note.get("incident_ref") or note.get("event"),
        "payload": {
            "summary": _subject(note)[:1024],
            "severity": _PAGERDUTY_SEVERITY.get(str(note.get("severity")), "warning"),
            "source": note.get("gateway_id") or "metacrust-gateway",
            "component": note.get("failure_domain") or "",
            "custom_details": _generic_body(note),
        },
        "links": (
            [{"href": note["dashboard_url"], "text": "Open in gateway console"}]
            if note.get("dashboard_url") else []
        ),
    }


def _facts(note: dict[str, Any]) -> list[tuple[str, Any]]:
    facts: list[tuple[str, Any]] = []
    if note.get("incident_ref"):
        facts.append(("Incident", note["incident_ref"]))
    if note.get("failure_domain"):
        facts.append(("Likely failure domain", note["failure_domain"]))
    if note.get("started_at"):
        facts.append(("Started", note["started_at"]))
    if note.get("resolved_at"):
        facts.append(("Resolved", note["resolved_at"]))
    if note.get("buffered_records") is not None:
        facts.append(("Buffered records", f"{int(note['buffered_records']):,}"))
    affected = note.get("affected") or []
    if affected:
        facts.append(("Affected", ", ".join(str(a) for a in affected)))
    return facts


def _subject(note: dict[str, Any]) -> str:
    ref = note.get("incident_ref")
    title = note.get("title") or "Gateway notification"
    return f"MetaCrust Incident {ref} — {title}" if ref else f"MetaCrust — {title}"


# ── transport ────────────────────────────────────────────────────────────

def _post(url: str, body: dict[str, Any], channel: dict[str, Any]) -> None:
    import httpx  # lazy: optional on dev machines

    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    headers.update(channel.get("headers") or {})
    secret = str(channel.get("secret") or "")
    if secret:
        # Lets a generic receiver verify the request really came from us.
        headers["X-MetaCrust-Signature"] = "sha256=" + hmac.new(
            secret.encode("utf-8"), raw, hashlib.sha256
        ).hexdigest()

    response = httpx.post(url, content=raw, headers=headers, timeout=TIMEOUT_S)
    if response.status_code >= 400:
        raise RuntimeError(f"{response.status_code} {response.text[:200]}")


def _send_email(channel: dict[str, Any], note: dict[str, Any]) -> None:
    settings = channel.get("email") or {}
    host = str(settings.get("smtp_host") or "").strip()
    recipients = [a for a in (settings.get("to_addresses") or []) if a]
    if not host or not recipients:
        raise ValueError("email channel needs an SMTP host and at least one recipient")

    message = EmailMessage()
    message["Subject"] = _subject(note)
    message["From"] = settings.get("from_address") or settings.get("username") or "gateway@metacrust"
    message["To"] = ", ".join(recipients)
    lines = [note.get("message") or ""]
    facts = _facts(note)
    if facts:
        lines += ["", *[f"{key}: {value}" for key, value in facts]]
    if note.get("dashboard_url"):
        lines += ["", f"Open in the gateway console: {note['dashboard_url']}"]
    message.set_content("\n".join(lines))

    # Encryption is chosen explicitly rather than inferred from the port, so
    # what the operator selected is what actually happens on the wire.
    security = str(settings.get("security") or "starttls")
    port = int(settings.get("smtp_port") or 587)

    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_S, context=ssl.create_default_context()) as smtp:
            _authenticate(smtp, settings)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=TIMEOUT_S) as smtp:
        if security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        _authenticate(smtp, settings)
        smtp.send_message(message)


def _authenticate(smtp: smtplib.SMTP, settings: dict[str, Any]) -> None:
    username = str(settings.get("username") or "")
    password = str(settings.get("password") or "")
    if username and password:
        smtp.login(username, password)
